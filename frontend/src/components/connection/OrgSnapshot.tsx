import { motion } from 'framer-motion';
import { CalendarDays, Database, Gauge, Globe2, RefreshCw, Users } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '@/api/client';
import { useConnectionSnapshot, useRefreshSnapshot } from '@/api/queries';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { ConnectionSnapshot } from '@/types';
import { Button } from '../ui/Button';
import { AnimatedNumber } from '../ui/Visuals';

/** Re-renders every few seconds so "updated 20s ago" keeps ticking. */
function useNow(ms = 5_000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

function ago(iso: string, now: number) {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 10) return 'just now';
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ago`;
}

const usedColor = (pct: number) => (pct >= 85 ? 'rgb(var(--bad))' : pct >= 65 ? 'rgb(var(--warn))' : 'rgb(var(--good))');

function speed(ms: number) {
  if (ms < 600) return { label: 'Fast', color: 'rgb(var(--good))' };
  if (ms < 1800) return { label: 'Normal', color: 'rgb(var(--warn))' };
  return { label: 'Slow', color: 'rgb(var(--bad))' };
}

function Kpi({ icon, label, children, sub, delay }: { icon: ReactNode; label: string; children: ReactNode; sub?: ReactNode; delay: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.35 }} className="min-w-0 rounded-xl border border-line bg-surface p-3 sm:p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-ink-muted">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-soft text-brand">{icon}</span>
        {label}
      </div>
      <p className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">{children}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-subtle">{sub}</p>}
    </motion.div>
  );
}

/** What each limit is, in plain words, and when it resets. */
const LIMIT_INFO: Record<string, { what: string; resets: string }> = {
  DailyApiRequests: {
    what: 'Calls made to Salesforce’s API by every integration and app, including this health check. When it runs out, integrations stop working until it resets.',
    resets: 'Rolling 24 hours',
  },
  DataStorageMB: { what: 'Space used by records (Accounts, Contacts, Leads, Opportunities…). When full, no new records can be saved.', resets: 'Doesn’t reset' },
  FileStorageMB: { what: 'Space used by files, attachments and documents.', resets: 'Doesn’t reset' },
  DailyAsyncApexExecutions: { what: 'Background jobs run by code in your org (batch, future and queueable Apex).', resets: 'Rolling 24 hours' },
  DailyBulkV2QueryJobs: { what: 'Large data exports through the Bulk API (this health check uses them only for very large objects).', resets: 'Rolling 24 hours' },
  SingleEmail: { what: 'Emails sent by code or automation (not emails people send themselves).', resets: 'Daily' },
};

/** "<1%" instead of a misleading "0%" when something is used; one decimal under 10%. */
function pctText(used: number, max: number) {
  if (!max) return '—';
  const p = (100 * used) / max;
  if (used > 0 && p < 1) return '<1%';
  return p < 10 ? `${p.toFixed(1).replace(/\.0$/, '')}%` : `${Math.round(p)}%`;
}

function Limits({ limits }: { limits: ConnectionSnapshot['limits'] }) {
  if (!limits.length) return null;
  return (
    <div>
      <h3 className="mb-1 text-sm font-semibold">Org limits</h3>
      <p className="mb-2 text-xs text-ink-subtle">How much of each Salesforce allowance is used and how much is left. Green is fine; orange from 65% used; red from 85%.</p>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-muted/50 text-left text-[11px] uppercase tracking-wide text-ink-subtle">
            <tr>
              <th className="px-3 py-2">Limit</th>
              <th className="px-3 py-2 text-right">Used</th>
              <th className="px-3 py-2 text-right">Remaining</th>
              <th className="px-3 py-2 text-right">Limit</th>
              <th className="w-40 px-3 py-2">Usage</th>
            </tr>
          </thead>
          <tbody>
            {limits.map((l) => {
              const pct = l.max ? (100 * l.used) / l.max : 0;
              const info = LIMIT_INFO[l.key];
              return (
                <tr key={l.key} className="border-t border-line align-top">
                  <td className="px-3 py-2.5">
                    <p className="font-medium">{l.label}</p>
                    {info && <p className="mt-0.5 max-w-md text-xs text-ink-muted">{info.what} <span className="text-ink-subtle">Resets: {info.resets}.</span></p>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums">{fmtNumber(l.used)} <span className="text-xs text-ink-subtle">{l.unit}</span></td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right font-medium tabular-nums">{fmtNumber(Math.max(l.max - l.used, 0))}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-ink-muted">{fmtNumber(l.max)}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                        <motion.span className="block h-full rounded-full" style={{ background: usedColor(pct) }}
                          initial={{ width: 0 }} animate={{ width: `${Math.max(pct, l.used > 0 ? 1.5 : 0)}%` }} transition={{ duration: 0.9 }} />
                      </span>
                      <span className="w-10 text-right text-xs font-semibold tabular-nums" style={{ color: usedColor(pct) }}>{pctText(l.used, l.max)}</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Records({ records }: { records: ConnectionSnapshot['records'] }) {
  if (!records.length) return null;
  const top = Math.max(...records.map((r) => r.count));
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">Records by object</h3>
      <ul className="space-y-1.5">
        {[...records].sort((a, b) => b.count - a.count).map((r, i) => (
          <li key={r.name}>
            <Link to={`/data/${encodeURIComponent(r.name)}`} className="group grid grid-cols-[7.5rem,1fr,4.5rem] items-center gap-3 rounded-lg px-1 py-1 text-sm hover:bg-muted" title={`Open ${r.label} in Your Data`}>
              <span className="truncate text-ink-muted group-hover:text-ink">{r.label}</span>
              <span className="h-2 overflow-hidden rounded-full bg-muted">
                <motion.span
                  className="block h-full rounded-full bg-brand"
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.max(2, (100 * r.count) / top)}%` }}
                  transition={{ duration: 0.9, delay: 0.05 * i, ease: [0.16, 1, 0.3, 1] }}
                />
              </span>
              <span className="text-right tabular-nums font-medium">{fmtNumber(r.count)}</span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-subtle">Counts come from Salesforce’s own summary, which it updates every few hours.</p>
    </div>
  );
}

/** Live facts about the connected org: users, records, response time, limits. Refreshes every 5 minutes. */
export function OrgSnapshot({ orgId }: { orgId: string | null }) {
  const snap = useConnectionSnapshot(orgId, true);
  const refresh = useRefreshSnapshot(orgId);
  const busy = snap.isFetching || refresh.isPending;
  const now = useNow();
  const s = snap.data;

  const years = s?.orgCreated ? Math.floor((now - new Date(s.orgCreated).getTime()) / (365.25 * 86_400_000)) : null;
  const sp = s ? speed(s.responseMs) : null;

  return (
    <section className="card mt-6 overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="flex items-center gap-2 font-semibold">
            Live org snapshot
            <span className="inline-flex items-center gap-1.5 rounded-full bg-good-soft px-2 py-0.5 text-[11px] font-medium text-good">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-good opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-good" />
              </span>
              Live
            </span>
          </h2>
          <p className="text-xs text-ink-subtle">
            {s ? `Read from Salesforce ${ago(s.asOf, now)} · refreshes every 5 minutes` : 'Reading from Salesforce…'}
          </p>
        </div>
        <Button size="sm" icon={<RefreshCw className={cx('h-3.5 w-3.5', busy && 'animate-spin')} />} onClick={() => refresh.mutate()} disabled={busy}>
          {busy ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>

      {snap.error && !s ? (
        <div className="px-6 py-6 text-sm">
          <p className="text-ink-muted">Couldn’t read the live snapshot. {errorMessage(snap.error)}</p>
          <Button size="sm" className="mt-3" onClick={() => snap.refetch()}>Try again</Button>
        </div>
      ) : !s ? (
        <div className="grid gap-3 p-6 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-[104px] animate-pulse rounded-xl bg-muted" />)}
        </div>
      ) : (
        <div className="space-y-6 p-4 sm:p-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi icon={<Users className="h-4 w-4" />} label="Active users" delay={0} sub="Standard Salesforce licences in use">
              {s.activeUsers === null ? '—' : <AnimatedNumber value={s.activeUsers} />}
            </Kpi>
            <Kpi icon={<Database className="h-4 w-4" />} label="Records stored" delay={0.05} sub={s.objectCount ? `Across ${fmtNumber(s.objectCount)} objects` : undefined}>
              {s.totalRecords === null ? '—' : <AnimatedNumber value={s.totalRecords} />}
            </Kpi>
            <Kpi
              icon={<Gauge className="h-4 w-4" />}
              label="Salesforce response"
              delay={0.1}
              sub={sp && <span style={{ color: sp.color }} className="font-medium">{sp.label}</span>}
            >
              <AnimatedNumber value={s.responseMs} />
              <span className="ml-1 text-sm font-medium text-ink-subtle">ms</span>
            </Kpi>
            <Kpi
              icon={<CalendarDays className="h-4 w-4" />}
              label="Org created"
              delay={0.15}
              sub={years !== null ? (years < 1 ? 'Less than a year old' : `${years} year${years === 1 ? '' : 's'} old`) : undefined}
            >
              {s.orgCreated ? fmtDate(s.orgCreated) : '—'}
            </Kpi>
          </div>

          <Limits limits={s.limits} />
          <Records records={s.records} />

          {(s.timeZone || s.locale) && (
            <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-4 text-xs text-ink-muted">
              {s.timeZone && <span className="inline-flex items-center gap-1.5"><Globe2 className="h-3.5 w-3.5" /> Time zone {s.timeZone}</span>}
              {s.locale && <span>Locale {s.locale}</span>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
