# One-service image (used by Railway): builds the website, then runs the API, which also serves the website.
# Same domain for both, so no CORS and one Salesforce callback URL: https://<your-domain>/connection/callback
# For the multi-container setup (separate nginx + worker), see docker-compose.yml instead.

# --- 1. Website ---
FROM node:20-alpine AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. API (+ the built website) ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    DATA_DIR=/data
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=web /src/dist ./static
# Local data lives under /data (uploaded CSV/Excel files; the key file and SQLite database when TOKEN_ENCRYPTION_KEY /
# DATABASE_URL aren't set): mount a volume there so it survives redeploys. Runs as root: Railway mounts volumes as root.
RUN mkdir -p /data/uploads

EXPOSE 8000
# Railway sets PORT; locally it defaults to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
