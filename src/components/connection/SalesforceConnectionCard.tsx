import { motion } from 'framer-motion';
import {
  Activity,
  CalendarClock,
  Check,
  Cloud,
  CloudOff,
  Code2,
  Copy,
  ExternalLink,
  Fingerprint,
  Gauge,
  Globe2,
  PlugZap,
  RefreshCw,
  ShieldCheck,
  Unplug,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { cx, fmtAgo, fmtDateTime, fmtNumber } from '@/lib/format';
import type { ConnectionSnapshot, SalesforceConnection } from '@/types';
import { Button } from '../ui/Button';

type Status = SalesforceConnection['status'];

const THEME: Record<Status, { ring: string; glow: string; text: string; dot: string; label: string }> = {
  connected: { ring: 'border-good/25', glow: 'from-good/10', text: 'text-good', dot: 'bg-good', label: 'Connected' },
  expired: { ring: 'border-warn/30', glow: 'from-warn/10', text: 'text-warn', dot: 'bg-warn', label: 'Timed out' },
  error: { ring: 'border-bad/30', glow: 'from-bad/10', text: 'text-bad', dot: 'bg-bad', label: 'Needs attention' },
  disconnected: { ring: 'border-line', glow: 'from-muted', text: 'text-ink-muted', dot: 'bg-ink-subtle', label: 'Not connected' },
};

/** Re-renders every 30s so "checked 2 min ago" stays true. */
function useTick(ms = 30_000) {
  const [, set] = useState(0);
  useEffect(() => {
    const t = setInterval(() => set((n) => n + 1), ms);
    return () => clearInterval(t);
  }, [ms]);
}

/** Platform ⇄ Salesforce with data packets flowing while connected (faster while checking). */
function LinkVisual({ status, checking, orgLabel }: { status: Status; checking: boolean; orgLabel: string | null }) {
  const active = status === 'connected';
  const broken = status === 'expired' || status === 'error';
  const line = active ? 'rgb(var(--good))' : broken ? 'rgb(var(--warn))' : 'rgb(var(--line))';
  const speed = checking ? 0.9 : 2.6;
  return (
    <div className="flex shrink-0 items-start justify-center gap-1">
      <div className="flex w-20 flex-col items-center gap-2">
        <motion.span
          className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-brand text-white shadow-lg shadow-brand/30"
          animate={active ? { y: [0, -3, 0] } : undefined}
          transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
        >
          <svg viewBox="0 0 32 32" className="h-9 w-9" aria-hidden="true">
            <path d="M9 21.5 16 8l7 13.5h-3.3L16 14l-3.7 7.5z" fill="currentColor" />
            <circle cx="16" cy="23.5" r="1.8" fill="#5eead4" />
          </svg>
        </motion.span>
        <span className="text-[11px] font-medium text-ink-muted">Aquarient</span>
      </div>

      <svg width="132" height="64" viewBox="0 0 132 64" className="mt-0 shrink-0" aria-hidden="true">
        <line x1="4" y1="24" x2="128" y2="24" stroke={line} strokeWidth="2" strokeDasharray="6 6" className={active ? 'animate-flow' : ''} opacity={active ? 0.55 : 1} />
        <line x1="4" y1="40" x2="128" y2="40" stroke={line} strokeWidth="2" strokeDasharray="6 6" className={active ? 'animate-flow' : ''} opacity={active ? 0.3 : 0.6} style={{ animationDirection: 'reverse' }} />
        {active &&
          [0, 1, 2].map((i) => (
            <motion.circle
              key={`out${i}`}
              r="3.5"
              cy="24"
              fill="rgb(var(--good))"
              initial={{ cx: 4, opacity: 0 }}
              animate={{ cx: [4, 128], opacity: [0, 1, 1, 0] }}
              transition={{ duration: speed, repeat: Infinity, delay: (i * speed) / 3, ease: 'linear' }}
            />
          ))}
        {active &&
          [0, 1].map((i) => (
            <motion.rect
              key={`in${i}`}
              width="7"
              height="5"
              rx="1.5"
              y="37.5"
              fill="#00a1e0"
              initial={{ x: 124, opacity: 0 }}
              animate={{ x: [124, 2], opacity: [0, 1, 1, 0] }}
              transition={{ duration: speed * 1.2, repeat: Infinity, delay: (i * speed) / 2 + 0.4, ease: 'linear' }}
            />
          ))}
        {broken && (
          <g transform="translate(58 24)">
            <circle r="10" fill="rgb(var(--warn-soft))" stroke="rgb(var(--warn))" strokeWidth="1.5" />
            <path d="M-3.5 -3.5 3.5 3.5M3.5 -3.5-3.5 3.5" stroke="rgb(var(--warn))" strokeWidth="2" strokeLinecap="round" />
          </g>
        )}
      </svg>

      <div className="flex w-20 flex-col items-center gap-2">
        <span className={cx('relative flex h-16 w-16 items-center justify-center rounded-2xl shadow-lg', active ? 'bg-[#00a1e0] text-white shadow-[#00a1e0]/30' : 'bg-muted text-ink-subtle shadow-none')}>
          {active && <span className="absolute inset-0 animate-pulse-ring rounded-2xl border-2 border-[#00a1e0]" />}
          {active ? <Cloud className="h-8 w-8" /> : <CloudOff className="h-8 w-8" />}
        </span>
        <span className="max-w-[5rem] truncate text-[11px] font-medium text-ink-muted" title={orgLabel ?? undefined}>{orgLabel ?? 'Salesforce'}</span>
      </div>
    </div>
  );
}

function StatusPill({ status, checking }: { status: Status; checking: boolean }) {
  const t = THEME[status];
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-full border bg-surface px-2.5 py-0.5 text-xs font-semibold', t.ring, t.text)}>
      <span className="relative flex h-2 w-2">
        {(status === 'connected' || checking) && <span className={cx('absolute inline-flex h-full w-full animate-ping rounded-full opacity-60', t.dot)} />}
        <span className={cx('relative inline-flex h-2 w-2 rounded-full', t.dot)} />
      </span>
      {checking ? 'Checking…' : t.label}
    </span>
  );
}

/** A live fact under the headline, e.g. "Response 307 ms". */
function Chip({ icon: Icon, children, tone = 'neutral', title }: { icon: LucideIcon; children: ReactNode; tone?: 'good' | 'warn' | 'bad' | 'neutral'; title?: string }) {
  return (
    <motion.span
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      title={title}
      className={cx(
        'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium',
        tone === 'good' && 'border-good/20 bg-good-soft text-good',
        tone === 'warn' && 'border-warn/20 bg-warn-soft text-warn',
        tone === 'bad' && 'border-bad/20 bg-bad-soft text-bad',
        tone === 'neutral' && 'border-line bg-surface text-ink-muted',
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {children}
    </motion.span>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(value).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        });
      }}
      className={cx('shrink-0 rounded-md p-1 transition hover:bg-muted', done ? 'text-good' : 'text-ink-subtle hover:text-ink')}
      aria-label={`Copy ${label}`}
      title={done ? 'Copied' : `Copy ${label}`}
    >
      {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function Detail({ icon: Icon, label, value, full, copy, index }: { icon: LucideIcon; label: string; value: string | null; full?: string | null; copy?: boolean; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.04 * index, duration: 0.3 }}
      className="group flex min-w-0 items-start gap-3 rounded-xl border border-line bg-surface p-3.5 transition hover:border-brand/30 hover:shadow-sm"
    >
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-muted text-ink-muted transition group-hover:bg-brand-soft group-hover:text-brand">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="label">{label}</p>
        <div className="mt-0.5 flex items-start gap-1">
          <p className={cx('min-w-0 break-all text-sm', value ? 'font-medium' : 'text-ink-subtle')} title={full ?? undefined}>
            {value ?? 'Not available'}
          </p>
          {copy && full && <CopyButton value={full} label={label} />}
        </div>
      </div>
    </motion.div>
  );
}

export function SalesforceConnectionCard({
  connection,
  onConnect,
  onDisconnect,
  onCheck,
  checking,
  snapshot,
}: {
  connection: SalesforceConnection;
  /** Omitted when the signed-in role can't connect orgs. */
  onConnect?: () => void;
  /** Omitted when the signed-in role can't disconnect (admins only). */
  onDisconnect?: () => void;
  onCheck: () => void;
  checking: boolean;
  /** Live facts (response time, API use) once loaded. */
  snapshot?: ConnectionSnapshot | null;
}) {
  useTick();
  const { status } = connection;
  const linked = status !== 'disconnected';
  const t = THEME[status];

  const api = snapshot?.limits.find((l) => l.key === 'DailyApiRequests');
  const apiUsed = api ?? (connection.apiRequestsMax && connection.apiRequestsRemaining !== null ? { used: connection.apiRequestsMax - connection.apiRequestsRemaining, max: connection.apiRequestsMax } : null);
  const apiPct = apiUsed && apiUsed.max ? Math.round((100 * apiUsed.used) / apiUsed.max) : null;
  const ms = snapshot?.responseMs;

  const details = [
    { icon: Fingerprint, label: 'Salesforce Org ID', value: connection.orgId, copy: true },
    { icon: Globe2, label: 'Instance URL', value: connection.instanceUrl?.replace(/^https:\/\//, '') ?? null, full: connection.instanceUrl, copy: true },
    { icon: Code2, label: 'API version', value: connection.apiVersion },
    { icon: UserRound, label: 'Connected by', value: connection.connectedBy },
    { icon: CalendarClock, label: 'Connected', value: connection.connectedAt ? `${fmtAgo(connection.connectedAt)} · ${fmtDateTime(connection.connectedAt)}` : null },
    { icon: Activity, label: 'Last connection check', value: connection.lastCheckedAt ? fmtAgo(connection.lastCheckedAt) : null, full: connection.lastCheckedAt ? fmtDateTime(connection.lastCheckedAt) : null },
  ];

  return (
    <section className={cx('card relative overflow-hidden border', t.ring)}>
      {/* soft status-coloured glow behind the header */}
      <div className={cx('pointer-events-none absolute inset-x-0 top-0 h-48 bg-gradient-to-b to-transparent', t.glow)} aria-hidden="true" />
      <div
        className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full opacity-[0.07] blur-2xl"
        style={{ background: status === 'connected' ? '#00a1e0' : 'rgb(var(--ink-subtle))' }}
        aria-hidden="true"
      />

      <div className="relative flex flex-col gap-6 p-6 lg:flex-row lg:items-center">
        <LinkVisual status={status} checking={checking} orgLabel={connection.organizationName} />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={status} checking={checking} />
            {linked && connection.environment && (
              <span className={cx('rounded-full border px-2.5 py-0.5 text-xs font-medium', connection.environment === 'sandbox' ? 'border-warn/30 bg-warn-soft text-warn' : 'border-line bg-surface text-ink-muted')}>
                {connection.environment === 'sandbox' ? 'Sandbox' : 'Production'}
              </span>
            )}
            {linked && connection.edition && <span className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-xs font-medium text-ink-muted">{connection.edition}</span>}
          </div>

          <h2 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">
            {linked ? connection.organizationName ?? 'Your Salesforce org' : 'Connect your Salesforce'}
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            {status === 'connected' && (
              <>
                <ShieldCheck className="-mt-0.5 mr-1 inline h-4 w-4 text-good" />
                Read-only access — we can read your data but never change it.
              </>
            )}
            {status === 'disconnected' && 'Sign in on Salesforce’s own page. We only ever read your data.'}
            {status === 'expired' && 'The connection timed out. Reconnect to keep running health checks — your past results are kept.'}
            {status === 'error' && (connection.errorMessage ?? 'The last connection check failed.')}
          </p>

          {status === 'connected' && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Chip icon={Activity} tone="good" title={connection.lastCheckedAt ? fmtDateTime(connection.lastCheckedAt) : undefined}>
                Healthy{connection.lastCheckedAt ? ` · checked ${fmtAgo(connection.lastCheckedAt)}` : ''}
              </Chip>
              {ms !== undefined && (
                <Chip icon={Gauge} tone={ms < 600 ? 'good' : ms < 1800 ? 'warn' : 'bad'} title="Time for one small Salesforce query">
                  Response {fmtNumber(ms)} ms
                </Chip>
              )}
              {apiPct !== null && apiUsed && (
                <Chip icon={RefreshCw} tone={apiPct >= 85 ? 'bad' : apiPct >= 65 ? 'warn' : 'neutral'} title={`${fmtNumber(apiUsed.used)} of ${fmtNumber(apiUsed.max)} API calls today`}>
                  API {apiPct}% used today
                </Chip>
              )}
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            {status !== 'connected' && onConnect && (
              <Button variant="primary" icon={<PlugZap className="h-4 w-4" />} onClick={onConnect}>
                {linked ? 'Reconnect Salesforce' : 'Connect Salesforce'}
              </Button>
            )}
            {linked && (
              <Button icon={<RefreshCw className={cx('h-4 w-4', checking && 'animate-spin')} />} onClick={onCheck} disabled={checking}>
                {checking ? 'Checking…' : 'Check connection'}
              </Button>
            )}
            {linked && connection.instanceUrl && (
              <a
                href={connection.instanceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-line bg-surface px-4 text-sm font-medium text-ink transition-all duration-150 hover:border-ink-subtle/40 hover:bg-muted active:scale-[0.98]"
              >
                <ExternalLink className="h-4 w-4" /> Open in Salesforce
              </a>
            )}
            {onDisconnect && linked && (
              <Button variant="danger" icon={<Unplug className="h-4 w-4" />} onClick={onDisconnect}>
                Disconnect
              </Button>
            )}
          </div>
        </div>
      </div>

      {linked && (
        <div className="relative grid gap-3 border-t border-line bg-muted/30 p-4 sm:grid-cols-2 sm:p-6 xl:grid-cols-3">
          {details.map((d, i) => (
            <Detail key={d.label} index={i} icon={d.icon} label={d.label} value={d.value} full={d.full ?? d.value} copy={d.copy} />
          ))}
        </div>
      )}

      {linked && apiUsed && apiPct !== null && !snapshot && (
        <div className="border-t border-line px-6 py-4">
          <div className="mb-1.5 flex justify-between text-xs">
            <span className="label">Daily API requests used</span>
            <span className="tabular-nums text-ink-muted">
              {fmtNumber(apiUsed.used)} / {fmtNumber(apiUsed.max)} ({apiPct}%)
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <motion.div
              className="h-full rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(apiPct, 1)}%` }}
              style={{ background: apiPct > 80 ? 'rgb(var(--bad))' : apiPct > 60 ? 'rgb(var(--warn))' : 'rgb(var(--good))' }}
            />
          </div>
        </div>
      )}
    </section>
  );
}
