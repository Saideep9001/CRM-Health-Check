import { motion } from 'framer-motion';
import { Check, Cloud, CloudOff, Copy, ExternalLink, PlugZap, RefreshCw, Unplug } from 'lucide-react';
import { useState } from 'react';
import { cx, fmtAgo, fmtDateTime, fmtNumber } from '@/lib/format';
import type { SalesforceConnection } from '@/types';
import { Badge, ConnectionStatusBadge } from '../ui/Badges';
import { Button } from '../ui/Button';

/** Animated link between the platform and Salesforce; flows only when connected. */
function LinkVisual({ status }: { status: SalesforceConnection['status'] }) {
  const active = status === 'connected';
  const broken = status === 'expired' || status === 'error';
  return (
    <div className="flex items-center justify-center py-2">
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand text-white shadow">
        <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
          <path d="M9 21.5 16 8l7 13.5h-3.3L16 14l-3.7 7.5z" fill="currentColor" />
          <circle cx="16" cy="23.5" r="1.8" fill="#5eead4" />
        </svg>
      </span>
      <svg width="120" height="24" viewBox="0 0 120 24" aria-hidden="true">
        <line
          x1="4"
          y1="12"
          x2="116"
          y2="12"
          stroke={active ? 'rgb(var(--good))' : broken ? 'rgb(var(--warn))' : 'rgb(var(--line))'}
          strokeWidth="2"
          strokeDasharray="6 6"
          className={active ? 'animate-flow' : ''}
        />
        {active && (
          <motion.circle
            r="4"
            cy="12"
            fill="rgb(var(--good))"
            initial={{ cx: 4 }}
            animate={{ cx: [4, 116, 4] }}
            transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          />
        )}
      </svg>
      <span
        className={cx(
          'relative flex h-14 w-14 items-center justify-center rounded-2xl shadow',
          active ? 'bg-[#00a1e0] text-white' : 'bg-muted text-ink-subtle',
        )}
      >
        {active && <span className="absolute inset-0 animate-pulse-ring rounded-2xl border-2 border-[#00a1e0]" />}
        {active ? <Cloud className="h-7 w-7" /> : <CloudOff className="h-7 w-7" />}
      </span>
    </div>
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
      className="shrink-0 rounded p-1 text-ink-subtle opacity-0 transition hover:bg-muted hover:text-ink focus:opacity-100 group-hover:opacity-100"
      aria-label={`Copy ${label}`}
      title={done ? 'Copied' : `Copy ${label}`}
    >
      {done ? <Check className="h-3.5 w-3.5 text-good" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

export function SalesforceConnectionCard({
  connection,
  onConnect,
  onDisconnect,
  onCheck,
  checking,
  hideUsage,
}: {
  connection: SalesforceConnection;
  /** Omitted when the signed-in role can't connect orgs. */
  onConnect?: () => void;
  /** Omitted when the signed-in role can't disconnect (admins only). */
  onDisconnect?: () => void;
  onCheck: () => void;
  checking: boolean;
  /** The live snapshot shows API usage itself, so the card can skip it. */
  hideUsage?: boolean;
}) {
  const { status } = connection;
  const linked = status !== 'disconnected';

  // [label, shown value, full value for the tooltip, copyable]
  const rows: [string, string | null, string | null, boolean][] = [
    ['Organization name', connection.organizationName, connection.organizationName, false],
    ['Salesforce Org ID', connection.orgId, connection.orgId, true],
    ['Instance URL', connection.instanceUrl?.replace(/^https:\/\//, '') ?? null, connection.instanceUrl, true],
    ['Edition', connection.edition, connection.edition, false],
    ['API version', connection.apiVersion, connection.apiVersion, false],
    ['Connected by', connection.connectedBy, connection.connectedBy, false],
    ['Connected', connection.connectedAt ? fmtAgo(connection.connectedAt) : null, connection.connectedAt ? fmtDateTime(connection.connectedAt) : null, false],
    ['Last connection check', connection.lastCheckedAt ? fmtAgo(connection.lastCheckedAt) : null, connection.lastCheckedAt ? fmtDateTime(connection.lastCheckedAt) : null, false],
  ];

  const usage =
    connection.apiRequestsMax && connection.apiRequestsRemaining !== null
      ? Math.round(((connection.apiRequestsMax - connection.apiRequestsRemaining) / connection.apiRequestsMax) * 100)
      : null;

  return (
    <section className="card overflow-hidden">
      <div className="flex flex-col gap-6 p-6 md:flex-row md:items-center">
        <LinkVisual status={status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">Salesforce connection</h2>
            <ConnectionStatusBadge status={status} />
            {linked && connection.environment && (
              <Badge tone={connection.environment === 'sandbox' ? 'warn' : 'neutral'}>{connection.environment === 'sandbox' ? 'Sandbox' : 'Production'}</Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-ink-muted">
            {status === 'connected' && `Connected to ${connection.organizationName}. We can read (but never change) your data.`}
            {status === 'disconnected' && 'Not connected yet.'}
            {status === 'expired' && 'Connection timed out. Please reconnect.'}
            {status === 'error' && (connection.errorMessage ?? 'The last connection check failed.')}
          </p>
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
              <a href={connection.instanceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-line bg-surface px-4 text-sm font-medium text-ink transition-all duration-150 hover:border-ink-subtle/40 hover:bg-muted active:scale-[0.98]">
                <ExternalLink className="h-4 w-4" /> Open in Salesforce
              </a>
            )}
            {onDisconnect && (
              <Button variant="danger" icon={<Unplug className="h-4 w-4" />} onClick={onDisconnect} disabled={!linked} title={linked ? undefined : 'Nothing to disconnect'}>
                Disconnect
              </Button>
            )}
          </div>
        </div>
      </div>

      <dl className="grid gap-px border-t border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        {rows.map(([label, value, full, copy]) => (
          <div key={label} className="group bg-surface px-6 py-4">
            <dt className="label">{label}</dt>
            <dd className={cx('mt-1 flex items-center gap-1 text-sm', value ? 'font-medium' : 'text-ink-subtle')} title={full ?? undefined}>
              <span className="min-w-0 truncate">{value ?? 'Not available'}</span>
              {copy && full && <CopyButton value={full} label={label} />}
            </dd>
          </div>
        ))}
      </dl>

      {usage !== null && !hideUsage && (
        <div className="border-t border-line px-6 py-4">
          <div className="mb-1.5 flex justify-between text-xs">
            <span className="label">Daily API requests used</span>
            <span className="tabular-nums text-ink-muted">
              {fmtNumber(connection.apiRequestsMax! - connection.apiRequestsRemaining!)} / {fmtNumber(connection.apiRequestsMax!)} ({usage}%)
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${usage}%`, background: usage > 80 ? 'rgb(var(--bad))' : usage > 60 ? 'rgb(var(--warn))' : 'rgb(var(--good))' }}
            />
          </div>
        </div>
      )}
    </section>
  );
}
