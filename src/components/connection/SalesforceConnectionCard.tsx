import { motion } from 'framer-motion';
import { Cloud, CloudOff, PlugZap, RefreshCw, Unplug } from 'lucide-react';
import { cx, fmtDateTime, fmtNumber } from '@/lib/format';
import type { SalesforceConnection } from '@/types';
import { ConnectionStatusBadge } from '../ui/Badges';
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

export function SalesforceConnectionCard({
  connection,
  onConnect,
  onDisconnect,
  onCheck,
  checking,
}: {
  connection: SalesforceConnection;
  onConnect: () => void;
  onDisconnect: () => void;
  onCheck: () => void;
  checking: boolean;
}) {
  const { status } = connection;
  const linked = status !== 'disconnected';

  const rows: [string, string | null][] = [
    ['Organization name', connection.organizationName],
    ['Salesforce Org ID', connection.orgId],
    ['Instance URL', connection.instanceUrl],
    ['Edition', connection.edition],
    ['API version', connection.apiVersion],
    ['Connected by', connection.connectedBy],
    ['Connected at', connection.connectedAt ? fmtDateTime(connection.connectedAt) : null],
    ['Last connection check', connection.lastCheckedAt ? fmtDateTime(connection.lastCheckedAt) : null],
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
          </div>
          <p className="mt-1 text-sm text-ink-muted">
            {status === 'connected' && `Connected to ${connection.organizationName}. We can read (but never change) your data.`}
            {status === 'disconnected' && 'Not connected yet.'}
            {status === 'expired' && 'Connection timed out. Please reconnect.'}
            {status === 'error' && (connection.errorMessage ?? 'The last connection check failed.')}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {status !== 'connected' && (
              <Button variant="primary" icon={<PlugZap className="h-4 w-4" />} onClick={onConnect}>
                {linked ? 'Reconnect Salesforce' : 'Connect Salesforce'}
              </Button>
            )}
            {linked && (
              <Button icon={<RefreshCw className={cx('h-4 w-4', checking && 'animate-spin')} />} onClick={onCheck} disabled={checking}>
                {checking ? 'Checking…' : 'Check connection'}
              </Button>
            )}
            <Button variant="danger" icon={<Unplug className="h-4 w-4" />} onClick={onDisconnect} disabled={!linked} title={linked ? undefined : 'Nothing to disconnect'}>
              Disconnect
            </Button>
          </div>
        </div>
      </div>

      <dl className="grid gap-px border-t border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        {rows.map(([label, value]) => (
          <div key={label} className="bg-surface px-6 py-4">
            <dt className="label">{label}</dt>
            <dd className={cx('mt-1 truncate text-sm', value ? 'font-medium' : 'text-ink-subtle')} title={value ?? undefined}>
              {value ?? 'Not available'}
            </dd>
          </div>
        ))}
      </dl>

      {usage !== null && (
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
