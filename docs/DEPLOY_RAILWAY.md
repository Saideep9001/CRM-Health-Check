# Deploying to Railway

One Railway service runs everything: the image built from the root `Dockerfile` serves the API (`/api/v1/...`)
and the website from the same domain. Health checks run inside it (`JOB_MODE=embedded`). Data goes in Railway's
PostgreSQL; uploaded CSV/Excel files go on a volume.

## 1. Create the project

1. Railway → **New Project** → **Deploy from GitHub repo** → pick this repository (branch `main`).
   Railway finds `railway.json` and builds the root `Dockerfile`.
2. In the project, **+ New → Database → PostgreSQL**.
3. On the app service: **Settings → Networking → Generate Domain** (e.g. `aquarient.up.railway.app`).
4. On the app service: **+ Volume**, mount path **`/data`** (keeps uploaded files across redeploys).

## 2. Variables (app service → Variables)

| Variable | Value |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference to the Postgres service) |
| `TOKEN_ENCRYPTION_KEY` | A Fernet key — generate once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep it: changing it makes saved Salesforce connections unreadable. |
| `SF_CLIENT_ID` / `SF_CLIENT_SECRET` | The Connected App's Consumer Key and Secret (or enter them later on the Connect Salesforce page). |
| `AUTH_REQUIRED` | `true` (the default) — the first visit asks you to create the admin account. |
| `FRONTEND_ORIGIN` | Optional. Defaults to `https://<the Railway domain>`. Set it if you add a custom domain, e.g. `https://health.example.com`. |
| `SMTP_HOST`, `SMTP_FROM`, … | Optional, for alert email (see `backend/.env.example`). |

Already set by the image: `STATIC_DIR=/app/static`, `UPLOAD_DIR=/data/uploads`. Railway sets `PORT`.

## 3. Salesforce Connected App

In Salesforce (Setup → App Manager → your Connected App → Callback URL) add:

```
https://<your-domain>/connection/callback
```

The exact URL is also printed in the deploy logs at start-up ("OAuth callback URL …").

## 4. Deploy and check

- Every push to `main` redeploys. The health check is `GET /api/v1/health`.
- Database tables are created and upgraded automatically on start-up.
- Open `https://<your-domain>` → create the admin account → Connect Salesforce (or upload a CSV/Excel file).

## Notes

- To scale checks out, use the multi-container setup instead (`docker-compose.yml`: API + workers with
  `JOB_MODE=external` + nginx website); on Railway that means separate services from the same repo.
- Uploaded data is on the `/data` volume, one SQLite file per upload; removing an upload in the app deletes it.
