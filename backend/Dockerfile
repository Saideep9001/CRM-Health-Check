# Backend API and worker image. The same image runs both:
#   API:    uvicorn app.main:app --host 0.0.0.0 --port 8000
#   Worker: python -m app.worker
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 aquarient && chown -R aquarient /app
USER aquarient

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
