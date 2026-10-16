# Aquarient CRM Health — Backend API Contract

The frontend calls these endpoints through `src/api/endpoints.ts`. TypeScript shapes live in
`src/types/index.ts` and are the source of truth for field names.

- **Base URL:** `VITE_API_BASE_URL` (default `/api/v1`; Vite proxies `/api` to `VITE_API_PROXY_TARGET` in development).
- **Format:** JSON, **camelCase** field names (use a Pydantic alias generator), ISO-8601 UTC timestamps.
- **Auth:** cookie session (`credentials: include`). See *Authentication* below.
- **Errors:** FastAPI default `{ "detail": "message" }` or the validation list. The UI shows `detail` to the user.
  `502/503/504` are treated as "service unavailable".
- **Lists:** `Paginated<T>` = `{ items, total, page, pageSize }`. Query parameters: `page`, `pageSize`, `sort` (e.g. `-createdAt`), and filters.
- **Stable keys:** category ids (`data-quality`, `workflows`, `reporting`, `user-adoption`, `quoting`, `integrations`)
  and area ids (`area-1` … `area-21`) must match `src/config/categories.ts`.

## Authentication

Sessions use an **HttpOnly, Secure, SameSite=Lax** cookie set by the backend; the frontend never handles tokens.
Every protected endpoint returns `401` when the session is missing or expired — the app then redirects to
`/login?next=<path>`. `GET /me` is the session probe used by the route guard.

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/login` | `{ email, password, rememberMe }` | `UserProfile` + session cookie. `401` invalid credentials, `423` locked, `429` rate-limited. |
| POST | `/auth/logout` | — | `204`, clears the cookie |
| POST | `/auth/sso/start` | `{ email, redirectUri }` | `{ authorizationUrl }` — IdP resolved from the email domain. After SSO, the backend sets the session and redirects to `redirectUri` (`/login?next=…`); on failure append `?error=…&error_description=…`. |
| POST | `/auth/password/forgot` | `{ email }` | `202` always (never reveal whether an account exists) |

Recommended: CSRF protection for cookie-authenticated mutations (e.g. double-submit token header), login rate limiting, and account lockout.

## System

| Method | Path | Response |
|---|---|---|
| GET | `/health` | `ApiHealth` — `{ status, version, executableAreaIds[] }`. The wizard only enables areas listed in `executableAreaIds`. |

## Salesforce connection (OAuth 2.0 web-server flow)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/salesforce/connection` | — | `SalesforceConnection` (`status: "disconnected"` when none) |
| POST | `/salesforce/oauth/start` | `OAuthStartRequest` `{ environment, myDomain?, redirectUri }` | `{ authorizationUrl, state }` |
| POST | `/salesforce/oauth/callback` | `{ code, state, redirectUri }` | `SalesforceConnection` |
| POST | `/salesforce/connection/check` | — | `SalesforceConnection` (refreshed `lastCheckedAt`, limits) |
| DELETE | `/salesforce/connection` | — | `204`. Revokes the tokens. |
| GET | `/salesforce/app` | — | `SalesforceAppConfig` `{ configured, source: "ui"\|"env"\|null, clientIdPreview, callbackUrl, updatedAt }` |
| PUT | `/salesforce/app` | `{ clientId, clientSecret }` | `SalesforceAppConfig`. `422` on invalid keys. Saving a different key disconnects Salesforce. |
| DELETE | `/salesforce/app` | — | `SalesforceAppConfig`. Removes page-entered keys (falls back to `.env` keys, if any). |

Connected App keys can be entered on the Connect Salesforce page (stored encrypted) or set in `backend/.env`; page keys win.
The secret is never returned — only a masked key preview. `POST /salesforce/oauth/start` returns `501` when no keys are set.
Once sign-in is enabled, the `/salesforce/app` write endpoints must be restricted to admins.

The browser is redirected to `authorizationUrl` and comes back to `{origin}/connection/callback?code&state`.
The backend creates and validates `state`, exchanges the code, and stores the tokens. Tokens never reach the browser.
The Connected App's callback URL must be `https://<frontend-host>/connection/callback`.

## Assessments

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/assessments?status=&page=&pageSize=&sort=` | — | `Paginated<Assessment>` |
| POST | `/assessments` | `CreateAssessmentRequest` `{ name, connectionId, scope, notes? }` | `201 Assessment` (`status: queued`) |
| GET | `/assessments/{id}` | — | `Assessment`. The UI polls every 3 s while `queued`/`running` (`progress` 0–100, `currentStep`). |
| POST | `/assessments/{id}/cancel` | — | `Assessment` (`status: cancelled`) |
| GET | `/assessments/{id}/results` | — | `AssessmentResults` — scores, `categories[]`, `areas[]` with `indicators[]` |
| GET | `/assessments/{id}/findings?page=&pageSize=` | — | `Paginated<Finding>` |

`scope` = `{ categoryIds[], areaIds[], lookbackDays | null, staleLeadDays, stuckOpportunityDays, objects?: string[] | null }`.
`objects` (Data Quality only): Salesforce object API names to check, up to 15. Omitted = Account, Contact, Lead, Opportunity.
Other objects get generic checks (duplicates by name, key-field completeness, unused custom fields).
`AssessmentResults.objects[]` = `{ name, label, records, completeness, duplicates, problems }` per checked object, and
`Finding.objectName` names the object a problem is about (`null` for org-wide settings).
Runs in the background; only one health check can run at a time (`409` otherwise). `POST` returns `409` when
Salesforce isn't connected and `422` when none of the selected areas can run yet (`GET /health` →
`executableAreaIds`, currently `area-1` … `area-11` and `area-18` … `area-21`). Unsupported areas in a mixed selection come back as
`status: "skipped"`. Results are `404` until the check is `completed`. Runs cut off by a server restart are marked `failed`.
Each `AreaResult.indicators[].label` must match a label in that area's `indicators` list in `categories.ts`.
`CategoryResult.score` may be `null`; the UI then uses the mean of the assessed area scores.

## Findings

| Method | Path | Body | Response |
|---|---|---|---|
| PATCH | `/findings/{id}` | `{ status?, notes? }` | `Finding` |

## Reports

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/reports/export` | `ReportExportRequest` `{ type, format: "pdf"\|"csv", assessmentId, categoryId, from, to }` | Binary file (`application/pdf` or `text/csv`) |

The CSV of findings is also generated in the browser from the loaded findings. PDF generation is server-side only.

## Data explorer (read-only)

Browse the connected org. `409` when not connected/expired, `404` for an unknown object or record,
`424` when Salesforce rejects the request (message is safe to show).

| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/data/objects` | — | `DataObject[]` `{ name, label, labelPlural, custom, common, system, approxCount }` (queryable objects; common ones first) |
| GET | `/data/objects/{name}` | — | `DataObjectDetail` `{ name, label, labelPlural, custom, nameField, searchable, defaultColumns, approxCount, salesforceUrl, fields: DataField[] }` |
| GET | `/data/objects/{name}/records` | `fields` (comma list, max 25), `q` (name search), `sort`, `dir`, `cursor`, `ids` (comma list: only these records), `filters` (JSON `[{field, op, value}]`, checked against describe) | `DataRecordPage` `{ columns, records: [{ id, values, refNames }], totalSize, nextCursor }` (200 per page) |
| GET | `/data/objects/{name}/records/{id}` | — | `DataRecord` `{ id, values, refNames, salesforceUrl }` |
| GET | `/data/search` | `q` (2+ chars), `objects` (comma list; default the main objects) | `DataSearchGroup[]` `{ object, label, labelPlural, records: [{ id, name, detail }] }` (5 per object, one Salesforce search call) |
| POST | `/data/ask` | `{ question, objects?, context? }` | `DataAnswer` `{ question, object, label, labelPlural, filters: [{ field, op, value, label }], sort, dir, countOnly, ignored, total }`; 422 when no object can be told from the question |
| POST | `/data/refresh` | — | `204`. Clears cached object and field lists. |

Object and field names are checked against Salesforce describe results before use; search text is escaped.
Unknown fields are dropped. `cursor` must be a Salesforce `nextRecordsUrl` path.

## Help assistant

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/assistant/status` | — | `{ mode: "guide", model: null }` — the assistant is a built-in guide. The platform doesn't use AI services. |

| POST | `/assistant/crm-query` | `{ queryId }` | `CrmAnswer` — `{ id, title, summary, total, rows: {label, detail?, url?}[], salesforceUrl, asOf }`. `409` when Salesforce isn't connected (or the session expired), `422` for an unknown id, `502` when Salesforce rejects the query. |

**Live CRM questions (no AI).** `queryId` is one of the ids in `src/config/crmQuestions.ts` (`leads.open`, `leads.new`,
`leads.unassigned`, `leads.stale`, `leads.bySource`, `opps.open`, `opps.closingThisMonth`, `opps.overdue`, `opps.byStage`,
`opps.top`, `opps.wonThisQuarter`, `accounts.count`, `accounts.noContacts`, `contacts.noEmail`, `contacts.noAccount`).
The backend maps each id to a **fixed, read-only SOQL query** (reference: `dev-server/crmQueries.ts`) — never build SOQL from user
text. Run it with the requesting user's own Salesforce token so Salesforce sharing rules and field permissions apply.
`rows[].url` links to the record in Lightning (`{instanceUrl}/lightning/r/{Object}/{Id}/view`); lists are capped at 10 rows.


## Consultant features

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/portfolio` | — | `PortfolioOrg[]` (every saved or previously checked org: score, previousScore, trend, openProblems, criticalProblems, valueAtRisk = biggest single problem, running, schedule) |
| POST | `/salesforce/connections/{orgId}/activate` | — | `PortfolioOrg` — makes it the active org |
| DELETE | `/salesforce/connections/{orgId}` | — | 204 (past checks are kept; another org becomes active) |
| PUT | `/schedules/{orgId}` | `{ frequency: daily\|weekly\|monthly, enabled, areaIds?, alertEmail?, scoreDrop, alertNewCritical }` | `ScanSchedule` |
| DELETE | `/schedules/{orgId}` | — | 204 |
| POST | `/schedules/{orgId}/test-email` | — | 204, or 501 when SMTP isn't configured |
| GET | `/assessments/{id}/proposal` | `rate`, `currency` | `Proposal` `{ summary, hours, cost, weeks, valueAtRisk, phases[], lines[] }` |
| GET | `/assessments/{id}/benchmarks` | — | `Benchmarks` `{ peers, minPeers, ready, lines: [{ key, score, median, percentile }] }` |
| POST | `/findings/{id}/fix-plan` | — | `FixPlan` `{ summary, steps[], risks, effortHours }` from built-in playbooks |

`GET /assessments` returns the active org's checks by default; pass `allOrgs=true` for every org.
`GET /me/notifications` returns stored notifications (`kind: alert|info`); `POST /me/notifications/read` takes `{ ids }` (empty = all).
`GET /me/settings` also holds `branding`, `hourlyRate`, `currency`.

## Current user

| Method | Path | Body | Response |
|---|---|---|---|
| GET / PATCH | `/me` | `Partial<UserProfile>` | `UserProfile` |
| GET / PUT | `/me/settings` | `AppSettings` | `AppSettings` |
| GET | `/me/notifications` | — | `AppNotification[]` (`link` is an in-app path, e.g. `/results?assessment=…`) |
| POST | `/me/notifications/read` | `{ ids: string[] }` | `204` |
