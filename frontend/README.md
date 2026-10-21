# Aquarient CRM Health — Frontend (website)

React + TypeScript + Vite + Tailwind single-page app for assessing Salesforce Sales Cloud health.
The app shows only data returned by the backend API. It contains no sample or fabricated results.

## Run locally

**Easiest (Windows):** from the project's top folder, double-click `start-backend.bat`, then `start-dev.bat`
(or `start-all.bat` for both). Open http://localhost:5173.

The backend (Python FastAPI, in `../backend/`) handles the Salesforce connection and data. See
[../backend/README.md](../backend/README.md), including how to create the Salesforce Connected App.
`.env.local` has `DEV_API=false` so the website talks to the backend on port 8000; set `DEV_API=true`
to use the old built-in dev API instead.

Manual commands:

```bash
cd frontend
npm install
cp .env.example .env    # optional: point at your backend
npm.cmd run dev         # (use npm.cmd in PowerShell) http://localhost:5173 (proxies /api to VITE_API_PROXY_TARGET, default http://localhost:8000)
npm run build           # type-check + production build into dist/
```

If the backend isn't running, the app still loads. It shows "service unavailable" states and an onboarding checklist.

## Sign-in

Sign-in is controlled by the **backend** (`AUTH_REQUIRED` in `backend/.env`, on by default). The website asks the
backend at start-up (`/auth/setup-status`) and shows the sign-in page, first-admin setup, or opens directly to match.
Roles (admin, consultant, viewer) and per-org access are enforced on the server; admins manage people in the Admin Panel.

## Local development API

Until the FastAPI backend is deployed, `npm run dev` serves a **local development API** built into
the Vite dev server (`dev-server/devApi.ts`, enabled by `DEV_API=true`). It is never part of a production build.

1. Copy `.env.example` to `.env.local` (git-ignored) if you don't already have one.
2. Keep `DEV_API=true`. Open http://localhost:5173 — no sign-in needed.
3. Only if you set `VITE_AUTH_REQUIRED=true`: sign in at `/login` with `DEV_LOGIN_EMAIL` / `DEV_LOGIN_PASSWORD`.

What the local API does:

- **Sign-in, profile, settings:** real session cookies; profile and settings saved to `.dev-data/` (git-ignored).
- **Salesforce:** the real OAuth 2.0 + PKCE flow once `SF_CLIENT_ID` / `SF_CLIENT_SECRET` from a Connected App are set
  (callback URL `http://localhost:5173/connection/callback`). Tokens are held in memory only, so restarting the dev server disconnects you.
- **Assessments:** no diagnostic engine yet. Lists are empty and starting an assessment returns a clear "not available" message.
- **Not available locally:** password-reset email, SSO, and PDF generation.

To use a real backend instead, set `DEV_API=false` and `VITE_API_PROXY_TARGET`.

## Help assistant ("Ask Aqua")

A chat button sits in the bottom-right corner of every app page.

- **Built-in guide (default, free, offline):** answers from the app's own topics, areas, glossary, and FAQ, plus the user's live
  status (connection, latest score, top problems). Logic lives in `src/assistant/guide.ts`.
- **Live Salesforce data (no AI):** once Salesforce is connected, Aqua answers 15 everyday questions — open leads,
  unassigned or quiet leads, lead sources, pipeline, deals closing this month, overdue deals, deals by stage, biggest deals,
  wins this quarter, accounts, accounts with no contacts, contacts with no email or no account. Each maps to a fixed read-only
  lookup on the server (`dev-server/crmQueries.ts`); phrasings are matched in `src/config/crmQuestions.ts`. Ask
  "What can I ask about my data?" to see the full list.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `/api/v1` | Base path or URL of the FastAPI backend |
| `VITE_API_PROXY_TARGET` | `http://localhost:8000` | Dev-server proxy target (development only) |
| `VITE_AUTH_REQUIRED` | `false` | `true` requires signing in at `/login` |
| `DEV_API` | — | `true` serves the local development API instead of proxying |
| `DEV_LOGIN_EMAIL`, `DEV_LOGIN_PASSWORD` | — | Local sign-in account (dev API only) |
| `SF_CLIENT_ID`, `SF_CLIENT_SECRET` | — | Salesforce Connected App for the dev API's OAuth flow |

Production hosting must serve `index.html` for every client route (SPA fallback), including `/connection/callback`.

## Structure

- `src/api/` — HTTP client (typed `ApiError`), endpoint functions (backend integration points), React Query hooks
- `src/config/categories.ts` — the 6 categories and 21 diagnostic areas (single source of truth)
- `src/types/` — domain types and the API contract
- `src/lib/health.ts` — pure helpers that derive scores and counts from API results
- `src/components/` — layout, UI primitives, charts, domain components
- `src/pages/` — one file per route, including the OAuth callback and the New Assessment wizard
- `../docs/API_CONTRACT.md` — endpoint specification for the backend team

## Routes

| Path | Access | Page |
|---|---|---|
| `/` | Public | Home |
| `/login` | Public | Sign in (email/password, SSO, password reset) |
| `/dashboard`, `/connection`, `/assessment/**`, `/results`, `/reports`, `/history`, `/settings` | Open (signed in when `VITE_AUTH_REQUIRED=true`) | Application |

## Workflows

1. **Connect Salesforce** — choose an environment, then the OAuth redirect, then `/connection/callback` (the backend exchanges the code).
2. **New assessment** — choose the org, then the scope (MVP areas the engine reports as executable), then settings, then review, then start.
3. **Track progress** — Results and History poll running assessments and update when they complete.
4. **Review findings** — filter, sort and page through findings; update status and notes.
5. **Reports** — preview, print, export CSV (client-side) or PDF (server-side).
