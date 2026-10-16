# Aquarient CRM Health — Backend (FastAPI)

Implements the API in `../docs/API_CONTRACT.md` under `/api/v1`. This first release covers the
**Salesforce integration**:

- OAuth 2.0 web-server sign-in with **PKCE** (production, sandbox, and My Domain orgs)
- One-time, 10-minute `state` values; redirects only to the app's own `/connection/callback`
- Salesforce tokens **encrypted at rest** (Fernet) and never sent to the browser
- Automatic access-token refresh; the connection is marked *expired* if refresh fails
- Connection check (org details + daily API limits) and disconnect (revokes the token at Salesforce)
- The 15 read-only data questions for "Ask Aqua" (`app/salesforce/crm_queries.py`)
- Profile, settings, notifications, and empty assessment lists so every page works

Not yet included: server-side PDF files (reports print to PDF from the browser) and sign-in. The platform doesn't use AI services.

## Run it

Double-click **`start-backend.bat`** in the project folder (first run installs everything), then
start the website with **`start-dev.bat`**. Or manually:

```bash
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000/api/v1/health · interactive docs: http://localhost:8000/docs
- The website (`npm run dev`) forwards `/api` to port 8000 when `.env.local` has `DEV_API=false`.

Run the tests (they use a fake Salesforce, no real org needed):

```bash
cd backend
.venv\Scripts\python -m pytest -q
```

## Create the Salesforce Connected App (one time)

You need Salesforce admin access (a free Developer Edition org works for testing).

1. In Salesforce: **Setup → App Manager → New Connected App** (or **New External Client App** in newer orgs).
2. Fill in a name (e.g. *Aquarient CRM Health*) and your contact email.
3. Tick **Enable OAuth Settings**.
4. **Callback URL:** `http://localhost:5173/connection/callback`
5. **Selected OAuth Scopes:** add
   - *Manage user data via APIs (api)*
   - *Perform requests at any time (refresh_token, offline_access)*
6. Tick **Require Proof Key for Code Exchange (PKCE)**, and **Require Secret for Web Server Flow**.
7. Save, wait a few minutes, then open **Manage Consumer Details** and copy the **Consumer Key** and **Consumer Secret**.
8. Open http://localhost:5173/connection and click **Connect Salesforce**. With no keys set yet, it opens the
   **Salesforce app setup** page (`/connection/setup`): paste them there and click **Save keys**.
   (The Callback URL to use in step 4 is shown there with a Copy button.)
9. You're taken back and the Connect dialog opens. Later, use **Manage Salesforce app keys** in that dialog to change them.

The keys are stored encrypted in the database; the secret is never sent back to the browser.
You can still put them in `backend/.env` instead (`SF_CLIENT_ID`, `SF_CLIENT_SECRET`) — keys entered
on the page take priority. Saving a different Consumer Key disconnects the current Salesforce org.

The user who connects should have **API Enabled** in their profile or permission set. Their own
Salesforce permissions decide what the app can read.

## Configuration (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `SF_CLIENT_ID`, `SF_CLIENT_SECRET` | — | Connected App keys (optional — can be entered on the Connect Salesforce page instead) |
| `SF_API_VERSION` | `v61.0` | Salesforce REST API version |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Allowed OAuth redirect origin and CORS origin |
| `TOKEN_ENCRYPTION_KEY` | auto in dev | Fernet key for encrypting tokens. **Set it in production.** |
| `DATABASE_URL` | `backend/.data/aquarient.db` | SQLAlchemy URL (SQLite locally; Postgres in production) |
| `LOCAL_USER_NAME`, `LOCAL_USER_EMAIL` | — | Profile shown until sign-in is enabled |
| `SCHEDULER_ENABLED` | `true` | Workers queue scheduled checks when they're due |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` | — / `587` / `true` | Alert email. Nothing is emailed unless `SMTP_HOST` and `SMTP_FROM` are set; alerts always appear in the app |

## Health checks

All 21 areas run automatically. Data Quality (areas 1–2) runs automatically; the checks come from the Aquarient RevenueOps Consultant Guide.
Each check is a fixed, read-only SOQL query in `app/engine/data_quality.py`. Fields an org doesn't have are skipped.

| Area | Indicators |
|---|---|
| 1. Duplicates, Key Fields & Standardization | Duplicate Accounts (name / website), Contacts and open Leads (email); Missing Email; Missing Phone; country/state spelling variants and whether State & Country picklists are on |
| 2. Redundant Fields & Scorecard | Key-field completeness; missing values; custom fields that look outdated or are never/rarely filled (up to 30 per object); Accounts without Contacts; overall scorecard |

Workflows & Automation (areas 3–7) is in `app/engine/workflows.py`:

| Area | Indicators |
|---|---|
| 3. Lead Assignments & Sales Progression | Leads owned by a queue; stale open Leads (setting: stale after N days); overdue open deals with value and owners; active Lead Assignment Rule and Lead automation (setup); deals with no Amount and Opportunity validation rules (setup) |
| 4. Account Hierarchies & Contact Relationships | Accounts with no Contacts and no deals; Contacts with no Account; open deals with no contact roles; Parent Account use and Contacts-to-Multiple-Accounts |
| 5. Sales Path & Feedback Loops | Stuck deals (setting: stuck after N days, by last stage change); missing Next Step; lost deals with no reason (finds the lost-reason field by name); Path guidance per open stage (setup) |
| 6. Activity Capture & Web-to-Lead | People who own open deals/leads with no tasks or events in 14 days (bots and integration users excluded); website leads stopped arriving; active email templates; open deals with no activity in 30 days |
| 7. Validation Rules & Required Fields | Core objects with no validation rules and vague error messages (setup); important optional fields that are often empty; placeholder values (“test”, “na”, “tbd”…); crowded or fragmented layouts (setup) |

Reporting & Dashboards (areas 8–11) is in `app/engine/reporting.py`:

| Area | Indicators |
|---|---|
| 8. Unused reports & leadership insights | Your own reports not run in 180 days and dashboards not opened in 180 days (package ones excluded; dashboard view dates are per connected user); unfiled or copy/test-named reports; whether reports exist for pipeline, forecast, win rate, rep activity, lead conversion |
| 9. Activity, handoffs & deal progress | Reps with fewer than 5 activities in 30 days; open deals with no open task; new deals with no Lead Source and Lead Status history tracking; deals that never left their first stage |
| 10. Regions, stuck & lost deals | Stuck and overdue deals plus whether any report tracks them; region field on deals; lost deals (12 months) with no reason and whether losses are analysed |
| 11. Win-loss & upsell | Win-rate report and lost-reason field; competitors recorded on closed deals; open deals with no products; customers who bought only one product family |

User Adoption & Enablement (areas 12–14) is in `app/engine/adoption.py`. Adoption is measured against each rep's own records, not just logins:

| Area | Indicators |
|---|---|
| 12. Logins & low adopters | People not logged in for 30+ days (full Salesforce licences priced at an assumed $165/user/month list); weekly login share; reps with little activity or mostly stale deals (with the pipeline value at risk); reps whose deals are often overdue or have no next step |
| 13. Roles, permissions & profiles | Public read/write sharing on deals and leads; unused custom permission sets; profiles used by one or two people; reps without a role and very deep hierarchies; people with Modify All Data |
| 14. Usability | Custom fields on core objects without help text; custom Lightning home page; list views that are cluttered or never opened; people still on Classic |

Quoting & Opportunity Product Management (areas 15–17) is in `app/engine/quoting.py` and works with standard Quotes and Salesforce CPQ:

| Area | Indicators |
|---|---|
| 15. Products & price books | Open deals with no products; active products with no standard price or code; retired products on open deals; empty price books and zero prices; won deals (12 months) with no products and products with no family |
| 16. Quotes & CPQ | CPQ migration readiness (Revenue Cloud complexity from price/product rules, scripts, discount schedules, approval rules); quotes turned off; open deals whose quotes aren't synced/primary; 50%+ deals with no quote; expired synced quotes and month-old drafts |
| 17. Approvals & discounts | Pending approvals and ones waiting 3+ days; discount leakage on won deals (list price vs. sold, by rep and product); no approval process for discounts; deals with 20%+ off that have no approval (approval history on the deal or quote, or a quote marked Approved) |

Integrations, API & Data Flow (areas 18–21) is in `app/engine/integrations.py`:

| Area | Indicators |
|---|---|
| 18. Marketing automation & lead flow | Marketing platform installed/connected (Pardot, HubSpot, Marketo…); new leads missing email or source; deals with no Primary Campaign Source; dedicated integration users and ones with admin rights |
| 19. ERP / finance & order flow | Account External ID field and how many Accounts lack it; won deals with no ERP/order reference or Order; orders or finance objects present; ERP/iPaaS connected |
| 20. API governance & health | Daily API use; other limits 80%+ used; connected apps with access unused for 90+ days; failed Apex jobs in 7 days |
| 21. Data warehouse & BI | BI/warehouse tools connected; business objects over 1M records (system metadata excluded); data and file storage use; reports sharing the same name |

Setup checks read the Tooling API and need “View Setup and Configuration”; without it they're skipped with a note.

Each indicator is scored 0–100; an area's score is the average, and problems are created when a score drops
below a threshold (severity: under 40 critical, under 60 high, under 80 medium, otherwise low).
Add new areas by writing checks in `app/engine/` and registering them in `runner.AREAS`.

Deeper outcome checks (`app/engine/deep.py`) are added to existing areas: nearly-empty custom fields that reports, flows or
code depend on (Dependency API, area 2); legacy Process Builders/Workflow Rules, objects automated by several tools, and flows
paused 7+ days (area 7); reports filtering on retired picklist values or nearly-empty fields, reports that error because a field
is gone (permission errors aren't counted), dashboards running as inactive users (area 8); stages mapped to the wrong forecast
category and open deals counted as Closed (area 10); and a 0–100 sync health score — integrations that stopped writing, duplicates
created by integration users, failed jobs (area 20).

## Consultant features

- **Portfolio** — several orgs can be connected; one is *active* (data explorer, new checks, dashboard and history use it).
  `GET /portfolio` lists every org with score, trend, open/critical problems, biggest single value at risk and schedule.
  Checks always run against their own org's connection.
- **Scheduled checks & alerts** — `PUT /schedules/{orgId}` (daily/weekly/monthly). Workers queue due schedules (claimed with a
  conditional update, so never twice). After every check, alerts are raised when the score drops by the schedule's threshold or
  new critical problems appear; they show under the bell and, if SMTP is configured, are emailed.
- **Proposal (SOW)** — `GET /assessments/{id}/proposal?rate=` drafts three phases with estimated hours per problem
  (`ai.estimate_hours`), cost and timeline; the Reports page lets you edit hours, leave items out, print or export.
- **White-label reports** — logo, company name, colour, prepared-by and footer in Settings; applied to every report.
- **Benchmarks** — `GET /assessments/{id}/benchmarks` ranks a check against the latest check of every other org in the
  workspace once there are at least 3. No data leaves the workspace.
- **Fix plans** — `POST /findings/{id}/fix-plan` returns step-by-step instructions from built-in playbooks (`app/playbooks.py`).

## Database & migrations

- **SQLite** (`backend/.data/aquarient.db`) is the default for one person's laptop. Use **PostgreSQL** for anything shared:
  `DATABASE_URL=postgresql+psycopg://user:password@host:5432/aquarient`.
- The schema is managed by **Alembic** (`backend/migrations`). The API (and each worker) upgrades the database to the
  latest version on start-up, so there's nothing to run by hand. A database created before migrations existed is
  recognised and adopted automatically.
- To change the schema: edit `app/models.py`, then from `backend/` run
  `.venv\Scripts\alembic revision --autogenerate -m "what changed"`, review the new file in `migrations/versions`, and commit it.
  `tests/test_jobs.py` fails if the models and migrations ever drift apart.

## Health check jobs

Health checks run from a **queue in the database**: creating a check stores it as `queued`, and a worker claims it
(`SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL, so several workers never pick the same one).

| `JOB_MODE` | Where checks run | Use for |
|---|---|---|
| `embedded` (default) | Worker threads inside the API process | A laptop or a single server — just run `start-backend.bat` |
| `external` | Separate `python -m app.worker` processes (`start-worker.bat`) | Production: scale workers independently, deploy the API without interrupting checks |
| `inline` | Right after the request | Automated tests only |

While a check runs, its worker writes a **heartbeat** every 15 s. If a worker dies (crash, restart, deploy), the check
is put back in the queue after `WORKER_HEARTBEAT_TIMEOUT_SECONDS` (120 s) and retried, up to `JOB_MAX_ATTEMPTS` (2),
then marked failed with a clear message. In embedded mode, checks interrupted by a restart are picked up immediately.
Only one check runs per Salesforce org at a time; different orgs run in parallel (`WORKER_THREADS` per worker).

## Deployment

- `docker-compose.yml` (project root) runs PostgreSQL, the API, scalable workers, and the website behind nginx:
  `docker compose up -d --build`, then `docker compose up -d --scale worker=3` for more capacity.
- `.github/workflows/ci.yml` runs the backend tests on SQLite **and a real PostgreSQL**, plus the frontend build, on every push.
- Run the suite against PostgreSQL locally with `TEST_DATABASE_URL=postgresql+psycopg://… python -m pytest`.

## Layout

```
app/
  main.py              FastAPI app, routers under /api/v1
  config.py            settings from env / backend/.env
  db.py, models.py     SQLAlchemy (connection, OAuth state, user prefs)
  crypto.py            token encryption
  schemas.py           camelCase API shapes (mirror src/types/index.ts)
  salesforce/
    oauth.py           PKCE, token exchange/refresh/revoke, identity
    client.py          read-only REST client with auto-refresh
    service.py         connect / check / disconnect lifecycle
    crm_queries.py     the 15 fixed Aqua data lookups
  routers/             salesforce, assistant, workspace (health, me, settings, assessments)
tests/                 pytest with a fake Salesforce (httpx MockTransport)
```

## Before production

- Set `TOKEN_ENCRYPTION_KEY` from a secret manager and use Postgres (`DATABASE_URL`).
- Serve over HTTPS and update `FRONTEND_ORIGIN` and the Connected App callback URL.
- Add sign-in and scope connections per customer workspace (currently one workspace, `default`).
- Restrict the **Salesforce app setup** endpoints (`PUT`/`DELETE /api/v1/salesforce/app`) to admins.
