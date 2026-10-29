/**
 * HTTP client for the Aquarient FastAPI backend.
 *
 * Base URL: VITE_API_BASE_URL (default "/api/v1", proxied by Vite in development —
 * see vite.config.ts). Auth: cookie-based session (credentials: "include"); add a
 * bearer token in `buildHeaders` if the backend adopts token auth.
 */

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '');
const DEFAULT_TIMEOUT_MS = 20_000;

export type ApiErrorKind = 'unavailable' | 'timeout' | 'http' | 'parse';

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    message: string,
    public status: number | null = null,
    public detail: unknown = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** True when the backend could not be reached at all. */
  get isUnavailable() {
    return this.kind === 'unavailable' || this.kind === 'timeout';
  }
  get isNotFound() {
    return this.status === 404;
  }
}

export const isApiError = (e: unknown): e is ApiError => e instanceof ApiError;

/** Human-readable message for any thrown value. */
export function errorMessage(e: unknown): string {
  if (isApiError(e)) return e.message;
  if (e instanceof Error) return e.message;
  return 'Unexpected error';
}

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions {
  query?: Query;
  body?: unknown;
  /** A file sent as-is (an upload), instead of a JSON body. */
  raw?: Blob;
  signal?: AbortSignal;
  responseType?: 'json' | 'blob';
  timeoutMs?: number;
}

function buildUrl(path: string, query?: Query) {
  const url = `${API_BASE_URL}${path}`;
  if (!query) return url;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  const s = qs.toString();
  return s ? `${url}?${s}` : url;
}

function buildHeaders(hasBody: boolean, raw = false): HeadersInit {
  const h: Record<string, string> = { Accept: 'application/json' };
  if (hasBody) h['Content-Type'] = raw ? 'application/octet-stream' : 'application/json';
  return h;
}

/** Extract FastAPI's `{ detail }` error payload (string or validation list). */
function parseDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object' || !('detail' in payload)) return null;
  const d = (payload as { detail: unknown }).detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => (x && typeof x === 'object' && 'msg' in x ? String(x.msg) : String(x))).join('; ');
  return null;
}

export async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort('timeout'), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  opts.signal?.addEventListener('abort', () => ctrl.abort(opts.signal?.reason));

  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      credentials: 'include',
      headers: buildHeaders(opts.body !== undefined || opts.raw !== undefined, opts.raw !== undefined),
      body: opts.raw ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
      signal: ctrl.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    if (ctrl.signal.reason === 'timeout') throw new ApiError('timeout', 'The Aquarient API did not respond in time.');
    if (opts.signal?.aborted) throw e;
    throw new ApiError('unavailable', 'Cannot reach the Aquarient API. Check that the backend service is running.');
  }
  clearTimeout(timer);

  if (res.status === 502 || res.status === 503 || res.status === 504) {
    throw new ApiError('unavailable', 'The Aquarient API is currently unavailable.', res.status);
  }

  if (!res.ok) {
    let payload: unknown = null;
    try {
      payload = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError('http', parseDetail(payload) ?? `Request failed (${res.status} ${res.statusText})`, res.status, payload);
  }

  if (opts.responseType === 'blob') return (await res.blob()) as T;
  // 202/204 and other success responses may legitimately have no body.
  const text = res.status === 204 ? '' : await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError('parse', 'The API returned an unexpected response.', res.status);
  }
}

export const http = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>('GET', path, { query, signal }),
  post: <T>(path: string, body?: unknown, timeoutMs?: number) => request<T>('POST', path, { body: body ?? {}, timeoutMs }),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, { body }),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
  delete: <T>(path: string) => request<T>('DELETE', path),
  blob: (path: string, body: unknown) => request<Blob>('POST', path, { body, responseType: 'blob', timeoutMs: 120_000 }),
  /** Send a file as the request body. */
  upload: <T>(path: string, file: Blob, query?: Query) => request<T>('POST', path, { raw: file, query, timeoutMs: 180_000 }),
};
