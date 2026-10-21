# Aquarient CRM Health & Data Quality Platform

Checks the health of a Salesforce Sales Cloud org — data quality, workflows, reporting, user adoption, quoting and
integrations — and tells you what to fix first. Read-only: it never changes anything in Salesforce.

## Project layout

| Folder | What's in it |
|---|---|
| [`backend/`](backend/README.md) | Python FastAPI service: Salesforce connection, health check engine, sign-in and roles, database and migrations, tests |
| [`frontend/`](frontend/README.md) | React + TypeScript website (Vite, Tailwind), its local dev API, and the web Docker image |
| `docs/` | API contract shared by both |
| `docker-compose.yml` | Production-style stack: PostgreSQL + API + workers + website |
| `start-*.bat` | One-click start scripts for Windows |

## Run locally (Windows)

1. Double-click **`start-all.bat`** — it opens the backend (port 8000) and the website (port 5173) in two windows.
   Or start them separately with `start-backend.bat` and `start-dev.bat`.
2. Open http://localhost:5173.

The first run sets up the Python environment (`backend/.venv`) and installs the website packages (`frontend/node_modules`).

### Add admins

With the backend stopped, from the `backend` folder:

```bash
.venv/Scripts/python -m app.manage add-admin person@company.com
```

You type a default password (not shown); each person chooses their own at first sign-in.

## Tests

```bash
cd backend && python -m pytest -q      # backend
cd frontend && npm run build           # website type-check and build
```
