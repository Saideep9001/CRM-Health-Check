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
import { useEffect, useId, useState, type ReactNode } from 'react';
import { cx, fmtAgo, fmtDateTime, fmtNumber } from '@/lib/format';
import type { ConnectionSnapshot, SalesforceConnection } from '@/types';
import { LogoGlyph } from '../ui/Brand';
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

/** Platform ⇄ Salesforce: one clean line with a single soft glow travelling along it while connected. */
function LinkVisual({ status, checking, orgLabel }: { status: Status; checking: boolean; orgLabel: string | null }) {
  const id = useId().replace(/:/g, '');
  const active = status === 'connected';
  const broken = status === 'expired' || status === 'error';
  const W = 140;
  const Y = 36;

  return (
    <div className="flex shrink-0 items-start justify-center">
      <div className="flex w-24 flex-col items-center gap-2">
        <span className="flex h-[72px] w-[72px] items-center justify-center rounded-2xl border border-line bg-white shadow-md">
          <LogoGlyph className="h-12 w-12" />
        </span>
        <span className="text-[11px] font-semibold text-ink-muted">Aquarient</span>
      </div>

      <svg width={W} height="72" viewBox={`0 0 ${W} 72`} className="shrink-0" aria-hidden="true">
        <defs>
          <linearGradient id={`line-${id}`} gradientUnits="userSpaceOnUse" x1="8" y1={Y} x2={W - 8} y2={Y}>
            <stop offset="0" stopColor="#058CC9" />
            <stop offset="1" stopColor="#00a1e0" />
          </linearGradient>
          <radialGradient id={`glow-${id}`}>
            <stop offset="0" stopColor="#fff" stopOpacity="1" />
            <stop offset="0.35" stopColor="#5fd3ff" stopOpacity="0.9" />
            <stop offset="1" stopColor="#00a1e0" stopOpacity="0" />
          </radialGradient>
        </defs>

        <line
          x1="8"
          y1={Y}
          x2={W - 8}
          y2={Y}
          stroke={active ? `url(#line-${id})` : broken ? 'rgb(var(--warn))' : 'rgb(var(--line))'}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={active ? undefined : '4 6'}
        />

        {active && (
          <motion.circle
            cy={Y}
            r="9"
            fill={`url(#glow-${id})`}
            initial={{ cx: 8 }}
            animate={{ cx: [8, W - 8] }}
            transition={{ duration: checking ? 1 : 3.2, repeat: Infinity, repeatType: 'reverse', ease: 'easeInOut' }}
          />
        )}

        {broken && (
          <g transform={`translate(${W / 2} ${Y})`}>
            <circle r="10" fill="rgb(var(--surface))" stroke="rgb(var(--warn))" strokeWidth="1.5" />
            <path d="M-3.5 -3.5 3.5 3.5M3.5 -3.5-3.5 3.5" stroke="rgb(var(--warn))" strokeWidth="2" strokeLinecap="round" />
          </g>
        )}
      </svg>

      <div className="flex w-24 flex-col items-center gap-2">
        <span className={cx('flex h-[72px] w-[72px] items-center justify-center rounded-2xl shadow-md', active ? 'bg-[#00a1e0] text-white' : 'bg-muted text-ink-subtle shadow-none')}>
          {active ? <Cloud className="h-9 w-9" /> : <CloudOff className="h-9 w-9" />}
        </span>
        <span className="max-w-[6rem] truncate text-[11px] font-semibold text-ink-muted" title={orgLabel ?? undefined}>
          {orgLabel ?? 'Salesforce'}
        </span>
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
  const uploaded = connection.environment === 'upload'; // CSV/Excel data, checked like an org

  const details = uploaded
    ? [
        { icon: Fingerprint, label: 'Upload ID', value: connection.orgId, copy: true },
        { icon: UserRound, label: 'Uploaded by', value: connection.connectedBy },
        { icon: CalendarClock, label: 'Uploaded', value: connection.connectedAt ? `${fmtAgo(connection.connectedAt)} · ${fmtDateTime(connection.connectedAt)}` : null },
      ]
    : [
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
                {connection.environment === 'sandbox' ? 'Sandbox' : uploaded ? 'Uploaded file' : 'Production'}
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
                {uploaded ? 'Data from an uploaded file, kept on this server and checked like a Salesforce org.' : 'Read-only access — we can read your data but never change it.'}
              </>
            )}
            {status === 'disconnected' && 'Sign in on Salesforce’s own page. We only ever read your data.'}
            {status === 'expired' && 'The connection timed out. Reconnect to keep running health checks — your past results are kept.'}
            {status === 'error' && (connection.errorMessage ?? 'The last connection check failed.')}
          </p>

          {status === 'connected' && !uploaded && (
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
            {linked && !uploaded && (
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
                {uploaded ? 'Remove upload' : 'Disconnect'}
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
