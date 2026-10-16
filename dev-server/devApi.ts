/**
 * Local development API — runs inside the Vite dev server (never in production builds).
 *
 * Implements the auth, user, and Salesforce-connection parts of docs/API_CONTRACT.md so the
 * frontend can be used end-to-end before the FastAPI backend exists:
 *   - Sign-in: one local account configured in .env.local (DEV_LOGIN_EMAIL / DEV_LOGIN_PASSWORD).
 *   - Salesforce: the real OAuth 2.0 web-server flow (with PKCE) when SF_CLIENT_ID / SF_CLIENT_SECRET
 *     are set; otherwise it responds that the Connected App isn't configured.
 *   - Assessments: no diagnostic engine exists yet, so lists are empty and creation returns 501.
 * Nothing here fabricates assessment results.
 */
import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import type { IncomingMessage, ServerResponse } from 'node:http';
import path from 'node:path';
import type { Plugin } from 'vite';
import { CRM_QUERY_IDS, runCrmQuery, type SoqlResult } from './crmQueries';

type Env = Record<string, string>;

interface Session {
  createdAt: number;
  expiresAt: number;
}

interface SfTokens {
  accessToken: string;
  refreshToken: string | null;
  instanceUrl: string;
  loginHost: string;
}

interface PendingOAuth {
  loginHost: string;
  environment: string;
  verifier: string;
  redirectUri: string;
  expiresAt: number;
}

const API_VERSION = 'v61.0';
const SESSION_COOKIE = 'aq_dev_session';

// ---------------------------------------------------------------------------
// Persistence for profile/settings (no secrets, no Salesforce tokens).
// ---------------------------------------------------------------------------

function createStore(file: string, email: string) {
  const defaults = {
    me: { id: 'local-user', name: email.split('@')[0].replace(/[._-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()), email, title: null as string | null, role: 'Administrator' as string | null },
    settings: {
      defaultLandingPage: 'dashboard',
      dateFormat: 'mdy',
      notifications: { assessmentCompleted: true, criticalFindings: true, weeklyDigest: false, productUpdates: false },
    },
  };
  let data = defaults;
  try {
    if (existsSync(file)) data = { ...defaults, ...JSON.parse(readFileSync(file, 'utf8')) };
  } catch {
    /* corrupt file — start fresh */
  }
  data.me.email = email; // login email is authoritative
  const save = () => {
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, JSON.stringify(data, null, 2));
  };
  return { get: () => data, save };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const send = (res: ServerResponse, status: number, body?: unknown) => {
  res.statusCode = status;
  if (body === undefined) return res.end();
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
};
const fail = (res: ServerResponse, status: number, detail: string) => send(res, status, { detail });

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  let raw = '';
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 1_000_000) throw new Error('Body too large');
  }
  return raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
}

const parseCookies = (req: IncomingMessage) =>
  Object.fromEntries((req.headers.cookie ?? '').split(';').map((p) => p.trim().split('=').map(decodeURIComponent)).filter((p) => p[0])) as Record<string, string>;

function safeEqual(a: string, b: string) {
  const ha = createHash('sha256').update(a).digest();
  const hb = createHash('sha256').update(b).digest();
  return timingSafeEqual(ha, hb);
}

const b64url = (buf: Buffer) => buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

function loginHostFor(environment: string, myDomain?: string) {
  if (environment === 'sandbox') return 'test.salesforce.com';
  if (environment === 'custom') {
    if (!myDomain || !/^[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*\.(my\.salesforce\.com|my\.salesforce-sites\.com|lightning\.force\.com)$/i.test(myDomain)) return null;
    return myDomain.toLowerCase();
  }
  return 'login.salesforce.com';
}

const DISCONNECTED = {
  id: null,
  status: 'disconnected',
  environment: null,
  organizationName: null,
  orgId: null,
  instanceUrl: null,
  edition: null,
  apiVersion: null,
  connectedBy: null,
  connectedAt: null,
  lastCheckedAt: null,
  apiRequestsRemaining: null,
  apiRequestsMax: null,
  errorMessage: null,
};

// ---------------------------------------------------------------------------
// Plugin
// ---------------------------------------------------------------------------

export function devApiPlugin(env: Env, root: string): Plugin {
  const email = (env.DEV_LOGIN_EMAIL ?? '').trim().toLowerCase();
  const password = env.DEV_LOGIN_PASSWORD ?? '';
  const sfClientId = env.SF_CLIENT_ID ?? '';
  const sfClientSecret = env.SF_CLIENT_SECRET ?? '';
  // Mirrors the frontend flag: without it, every request acts as the local user.
  const authRequired = env.VITE_AUTH_REQUIRED === 'true';
  const store = createStore(path.join(root, '.dev-data', 'local-api.json'), email || 'user@localhost');

  const sessions = new Map<string, Session>();
  const pendingOAuth = new Map<string, PendingOAuth>();
  const attempts = new Map<string, number[]>();
  let sf: SfTokens | null = null;
  let connection: Record<string, unknown> = { ...DISCONNECTED };

  const authed = (req: IncomingMessage) => {
    const sid = parseCookies(req)[SESSION_COOKIE];
    const s = sid ? sessions.get(sid) : undefined;
    if (!s || s.expiresAt < Date.now()) {
      if (sid) sessions.delete(sid);
      return false;
    }
    return true;
  };

  async function sfFetch(p: string, init?: RequestInit) {
    if (!sf) throw new Error('Not connected');
    const doFetch = () => fetch(`${sf!.instanceUrl}${p}`, { ...init, headers: { Authorization: `Bearer ${sf!.accessToken}`, Accept: 'application/json', ...(init?.headers ?? {}) } });
    let r = await doFetch();
    if (r.status === 401 && sf.refreshToken) {
      const t = await fetch(`https://${sf.loginHost}/services/oauth2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: sf.refreshToken, client_id: sfClientId, client_secret: sfClientSecret }),
      });
      if (!t.ok) throw Object.assign(new Error('Salesforce session expired'), { expired: true });
      const tj = (await t.json()) as { access_token: string; instance_url?: string };
      sf.accessToken = tj.access_token;
      if (tj.instance_url) sf.instanceUrl = tj.instance_url;
      r = await doFetch();
    }
    if (!r.ok) {
      // Salesforce returns [{ message, errorCode }]; surface the message (e.g. missing field access).
      let detail = '';
      try {
        const body = (await r.json()) as { message?: string }[];
        detail = body?.[0]?.message ? `: ${body[0].message}` : '';
      } catch {
        /* non-JSON error body */
      }
      throw new Error(`Salesforce API error ${r.status}${detail}`);
    }
    return r.json() as Promise<Record<string, unknown>>;
  }

  const soql = async (query: string) => (await sfFetch(`/services/data/${API_VERSION}/query?q=${encodeURIComponent(query)}`)) as unknown as SoqlResult;

  async function refreshLimits() {
    try {
      const limits = (await sfFetch(`/services/data/${API_VERSION}/limits`)) as { DailyApiRequests?: { Max: number; Remaining: number } };
      connection = {
        ...connection,
        status: 'connected',
        errorMessage: null,
        lastCheckedAt: new Date().toISOString(),
        apiRequestsMax: limits.DailyApiRequests?.Max ?? null,
        apiRequestsRemaining: limits.DailyApiRequests?.Remaining ?? null,
      };
    } catch (e) {
      const expired = (e as { expired?: boolean }).expired;
      connection = { ...connection, status: expired ? 'expired' : 'error', errorMessage: (e as Error).message, lastCheckedAt: new Date().toISOString() };
    }
  }

  async function handle(req: IncomingMessage, res: ServerResponse) {
    const url = new URL(req.url ?? '/', 'http://localhost');
    const p = url.pathname.replace(/\/+$/, '') || '/';
    const method = req.method ?? 'GET';
    const is = (m: string, route: string) => method === m && p === route;

    // ---- Public ----
    if (is('GET', '/health')) return send(res, 200, { status: 'ok', version: 'local-dev', executableAreaIds: [] });

    if (is('POST', '/auth/login')) {
      if (!email || !password) return fail(res, 503, 'Local sign-in is not configured. Set DEV_LOGIN_EMAIL and DEV_LOGIN_PASSWORD in .env.local and restart the dev server.');
      const ip = req.socket.remoteAddress ?? 'local';
      const recent = (attempts.get(ip) ?? []).filter((t) => t > Date.now() - 60_000);
      if (recent.length >= 5) return fail(res, 429, 'Too many sign-in attempts. Try again in a minute.');
      const body = await readJson(req);
      const ok = safeEqual(String(body.email ?? '').trim().toLowerCase(), email) && safeEqual(String(body.password ?? ''), password);
      if (!ok) {
        attempts.set(ip, [...recent, Date.now()]);
        return fail(res, 401, 'Invalid credentials');
      }
      attempts.delete(ip);
      const sid = b64url(randomBytes(32));
      const maxAge = body.rememberMe ? 30 * 86_400 : 12 * 3_600;
      sessions.set(sid, { createdAt: Date.now(), expiresAt: Date.now() + maxAge * 1000 });
      res.setHeader('Set-Cookie', `${SESSION_COOKIE}=${sid}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`);
      return send(res, 200, store.get().me);
    }
    if (is('POST', '/auth/logout')) {
      const sid = parseCookies(req)[SESSION_COOKIE];
      if (sid) sessions.delete(sid);
      res.setHeader('Set-Cookie', `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`);
      return send(res, 204);
    }
    if (is('POST', '/auth/password/forgot')) return fail(res, 501, 'Password reset email is not available on the local dev server. Change DEV_LOGIN_PASSWORD in .env.local instead.');
    if (is('POST', '/auth/sso/start')) return fail(res, 501, 'Single sign-on is not configured on the local dev server.');

    // ---- Everything else requires a session ----
    if (authRequired && !authed(req)) return fail(res, 401, 'Not authenticated');

    // Help assistant
    if (is('GET', '/assistant/status')) return send(res, 200, { mode: 'guide', model: null });
    if (is('POST', '/assistant/crm-query')) {
      const b = await readJson(req);
      const id = String(b.queryId ?? '');
      if (!CRM_QUERY_IDS.includes(id)) return fail(res, 422, 'Unknown question.');
      if (!sf || connection.status !== 'connected') return fail(res, 409, 'Salesforce isn’t connected. Connect it first to ask about your data.');
      try {
        return send(res, 200, await runCrmQuery(id, soql, sf.instanceUrl));
      } catch (e) {
        if ((e as { expired?: boolean }).expired) {
          connection = { ...connection, status: 'expired' };
          return fail(res, 409, 'Your Salesforce connection has timed out. Please reconnect.');
        }
        return fail(res, 502, `Salesforce couldn’t answer that. ${(e as Error).message}`);
      }
    }

    // User
    if (is('GET', '/me')) return send(res, 200, store.get().me);
    if (is('PATCH', '/me')) {
      const b = await readJson(req);
      const me = store.get().me;
      if (typeof b.name === 'string' && b.name.trim()) me.name = b.name.trim().slice(0, 120);
      if ('title' in b) me.title = typeof b.title === 'string' ? b.title.slice(0, 120) : null;
      if ('role' in b) me.role = typeof b.role === 'string' ? b.role.slice(0, 120) : null;
      // Email is the login identity on the dev server and can't be changed here.
      store.save();
      return send(res, 200, me);
    }
    if (is('GET', '/me/settings')) return send(res, 200, store.get().settings);
    if (is('PUT', '/me/settings')) {
      const b = await readJson(req);
      const cur = store.get().settings;
      const n = (b.notifications ?? {}) as Record<string, unknown>;
      if (['dashboard', 'results', 'reports'].includes(String(b.defaultLandingPage))) cur.defaultLandingPage = String(b.defaultLandingPage);
      if (['mdy', 'dmy', 'iso'].includes(String(b.dateFormat))) cur.dateFormat = String(b.dateFormat);
      for (const k of Object.keys(cur.notifications) as (keyof typeof cur.notifications)[]) if (typeof n[k] === 'boolean') cur.notifications[k] = n[k] as boolean;
      store.save();
      return send(res, 200, store.get().settings);
    }
    if (is('GET', '/me/notifications')) return send(res, 200, []);
    if (is('POST', '/me/notifications/read')) return send(res, 204);

    // Salesforce connection
    if (is('GET', '/salesforce/connection')) return send(res, 200, connection);
    if (is('POST', '/salesforce/oauth/start')) {
      if (!sfClientId || !sfClientSecret)
        return fail(res, 501, 'Salesforce Connected App is not configured. Set SF_CLIENT_ID and SF_CLIENT_SECRET in .env.local and restart the dev server.');
      const b = await readJson(req);
      const loginHost = loginHostFor(String(b.environment), typeof b.myDomain === 'string' ? b.myDomain : undefined);
      if (!loginHost) return fail(res, 422, 'Invalid My Domain.');
      const redirectUri = String(b.redirectUri ?? '');
      const state = b64url(randomBytes(24));
      const verifier = b64url(randomBytes(48));
      const challenge = b64url(createHash('sha256').update(verifier).digest());
      pendingOAuth.set(state, { loginHost, environment: String(b.environment), verifier, redirectUri, expiresAt: Date.now() + 10 * 60_000 });
      const q = new URLSearchParams({
        response_type: 'code',
        client_id: sfClientId,
        redirect_uri: redirectUri,
        scope: 'api refresh_token offline_access',
        state,
        code_challenge: challenge,
        code_challenge_method: 'S256',
        prompt: 'login consent',
      });
      return send(res, 200, { authorizationUrl: `https://${loginHost}/services/oauth2/authorize?${q}`, state });
    }
    if (is('POST', '/salesforce/oauth/callback')) {
      const b = await readJson(req);
      const pending = pendingOAuth.get(String(b.state));
      pendingOAuth.delete(String(b.state));
      if (!pending || pending.expiresAt < Date.now() || pending.redirectUri !== b.redirectUri) return fail(res, 400, 'Authorization state is invalid or expired. Please connect again.');
      const t = await fetch(`https://${pending.loginHost}/services/oauth2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          grant_type: 'authorization_code',
          code: String(b.code),
          client_id: sfClientId,
          client_secret: sfClientSecret,
          redirect_uri: pending.redirectUri,
          code_verifier: pending.verifier,
        }),
      });
      const tj = (await t.json()) as Record<string, string>;
      if (!t.ok) return fail(res, 400, `Salesforce rejected the authorization: ${tj.error_description ?? tj.error ?? t.status}`);
      sf = { accessToken: tj.access_token, refreshToken: tj.refresh_token ?? null, instanceUrl: tj.instance_url, loginHost: pending.loginHost };
      try {
        const idRes = await fetch(tj.id, { headers: { Authorization: `Bearer ${tj.access_token}` } });
        const identity = (await idRes.json()) as { organization_id?: string; display_name?: string; username?: string };
        const org = (await sfFetch(`/services/data/${API_VERSION}/query?q=${encodeURIComponent('SELECT Name, OrganizationType FROM Organization')}`)) as {
          records?: { Name: string; OrganizationType: string }[];
        };
        connection = {
          ...DISCONNECTED,
          id: identity.organization_id ?? 'salesforce',
          status: 'connected',
          environment: pending.environment,
          organizationName: org.records?.[0]?.Name ?? null,
          orgId: identity.organization_id ?? null,
          instanceUrl: tj.instance_url,
          edition: org.records?.[0]?.OrganizationType ?? null,
          apiVersion: API_VERSION,
          connectedBy: identity.display_name ?? identity.username ?? null,
          connectedAt: new Date().toISOString(),
        };
        await refreshLimits();
      } catch (e) {
        connection = { ...DISCONNECTED, status: 'error', errorMessage: `Connected, but reading org details failed: ${(e as Error).message}` };
      }
      return send(res, 200, connection);
    }
    if (is('POST', '/salesforce/connection/check')) {
      if (!sf) return send(res, 200, connection);
      await refreshLimits();
      return send(res, 200, connection);
    }
    if (is('DELETE', '/salesforce/connection')) {
      if (sf) {
        const token = sf.refreshToken ?? sf.accessToken;
        await fetch(`https://${sf.loginHost}/services/oauth2/revoke`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ token }),
        }).catch(() => undefined);
      }
      sf = null;
      connection = { ...DISCONNECTED };
      return send(res, 204);
    }

    // Assessments — no diagnostic engine in local development.
    if (is('GET', '/assessments')) {
      const pageSize = Number(url.searchParams.get('pageSize') ?? 100);
      return send(res, 200, { items: [], total: 0, page: 1, pageSize });
    }
    if (is('POST', '/assessments')) return fail(res, 501, 'The diagnostic engine is not available yet. Assessments can be run once the backend service is deployed.');
    if (method === 'GET' && p.startsWith('/assessments/')) return fail(res, 404, 'Assessment not found');
    if (method === 'POST' && /^\/assessments\/[^/]+\/cancel$/.test(p)) return fail(res, 404, 'Assessment not found');
    if (method === 'PATCH' && p.startsWith('/findings/')) return fail(res, 404, 'Finding not found');
    if (is('POST', '/reports/export')) return fail(res, 501, 'Report generation is not available on the local dev server.');

    return fail(res, 404, `No route for ${method} ${p}`);
  }

  return {
    name: 'aquarient-dev-api',
    apply: 'serve',
    configureServer(server) {
      const configured = !authRequired ? 'sign-in not required' : email && password ? `sign in as ${email}` : 'sign-in NOT configured (set DEV_LOGIN_EMAIL / DEV_LOGIN_PASSWORD in .env.local)';
      server.config.logger.info(`\n  Local dev API enabled at /api/v1 — ${configured}; Salesforce OAuth ${sfClientId ? 'configured' : 'not configured'}; assistant: built-in guide\n`);
      server.middlewares.use('/api/v1', (req, res) => {
        handle(req, res).catch((e: unknown) => {
          server.config.logger.error(`[dev-api] ${(e as Error).message}`);
          if (!res.headersSent) fail(res, 500, 'Local dev API error');
        });
      });
    },
  };
}
