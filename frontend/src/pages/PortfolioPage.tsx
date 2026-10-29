import { motion } from 'framer-motion';
import { ArrowDownRight, ArrowRight, ArrowUpRight, BellRing, Building2, CalendarClock, CircleDollarSign, LayoutDashboard, ListChecks, Loader2, Mail, Play, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { errorMessage } from '@/api/client';
import { useActivateOrg, useDeleteSchedule, usePortfolio, useRole, useSaveSchedule, useTestAlertEmail } from '@/api/queries';
import { Badge } from '@/components/ui/Badges';
import { Button } from '@/components/ui/Button';
import { CategoryIcon } from '@/components/ui/CategoryIcon';
import { Field, Select, Toggle } from '@/components/ui/Form';
import { Modal } from '@/components/ui/Overlay';
import { PageHeader, StaggerGrid, StaggerItem } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { Segmented } from '@/components/ui/Tabs';
import { AnimatedNumber, ScoreRing } from '@/components/ui/Visuals';
import { CATEGORIES, CATEGORY_COLORS } from '@/config/categories';
import { useToast } from '@/context/ToastContext';
import { cx, fmtCompact, fmtDate, fmtNumber } from '@/lib/format';
import type { PortfolioOrg, ScheduleFrequency } from '@/types';
import { DisconnectDialog } from '@/components/connection/DisconnectDialog';
import { ConnectModal } from './ConnectionPage';

const FREQ_LABEL: Record<ScheduleFrequency, string> = { daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly' };

function ScheduleModal({ org, onClose }: { org: PortfolioOrg; onClose: () => void }) {
  const s = org.schedule;
  const { notify } = useToast();
  const save = useSaveSchedule();
  const remove = useDeleteSchedule();
  const test = useTestAlertEmail();
  const [frequency, setFrequency] = useState<ScheduleFrequency>(s?.frequency ?? 'weekly');
  const [enabled, setEnabled] = useState(s?.enabled ?? true);
  const [email, setEmail] = useState(s?.alertEmail ?? '');
  const [drop, setDrop] = useState(s?.scoreDrop ?? 5);
  const [critical, setCritical] = useState(s?.alertNewCritical ?? true);

  const submit = () =>
    save.mutate(
      { orgId: org.orgId, body: { frequency, enabled, alertEmail: email.trim() || null, scoreDrop: drop, alertNewCritical: critical } },
      {
        onSuccess: (r) => {
          notify('Schedule saved', r.enabled && r.nextRunAt ? `Next check ${fmtDate(r.nextRunAt)}.` : 'Scheduled checks are paused.', 'success');
          onClose();
        },
        onError: (e) => notify('Couldn’t save the schedule', errorMessage(e), 'warning'),
      },
    );

  return (
    <Modal
      open
      onClose={onClose}
      title={`Scheduled checks · ${org.organizationName}`}
      description="Run a full health check automatically and get alerted when things get worse."
      footer={
        <>
          {s && (
            <Button variant="ghost" className="mr-auto" icon={<Trash2 className="h-4 w-4" />} onClick={() => remove.mutate(org.orgId, { onSuccess: onClose })}>
              Remove schedule
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save schedule'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <p className="mb-1.5 text-sm font-medium">How often</p>
          <Segmented<ScheduleFrequency>
            layoutId="freq-seg"
            value={frequency}
            onChange={setFrequency}
            options={[{ id: 'daily', label: 'Daily' }, { id: 'weekly', label: 'Weekly' }, { id: 'monthly', label: 'Monthly' }]}
          />
          <p className="mt-1 text-xs text-ink-subtle">Each run checks all 21 areas and uses a few hundred Salesforce API calls.</p>
        </div>
        <Toggle checked={enabled} onChange={setEnabled} label="Schedule is on" description="Pause it any time without losing the settings." />
        <div className="rounded-xl border border-line p-3">
          <p className="mb-2 flex items-center gap-2 text-sm font-semibold"><BellRing className="h-4 w-4 text-brand" /> Alerts</p>
          <Field label="Alert when the health score drops by" hint="Compared with the previous check of this org.">
            <div className="flex items-center gap-2">
              <input type="number" min={1} max={100} value={drop} onChange={(e) => setDrop(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} className="input w-24" />
              <span className="text-sm text-ink-muted">points or more</span>
            </div>
          </Field>
          <Toggle checked={critical} onChange={setCritical} label="Alert on new critical problems" description="Problems that weren’t there in the previous check." />
          <Field label="Also email alerts to (optional)" hint="Alerts always appear under the bell. Email needs SMTP set up on the server.">
            <div className="flex gap-2">
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" className="input" />
              <Button
                size="sm"
                icon={<Mail className="h-3.5 w-3.5" />}
                disabled={!s?.alertEmail || test.isPending}
                title={s?.alertEmail ? 'Send a test email' : 'Save an email address first'}
                onClick={() => test.mutate(org.orgId, { onSuccess: () => notify('Test email sent', s?.alertEmail ?? '', 'success'), onError: (e) => notify('Couldn’t send', errorMessage(e), 'warning') })}
              >
                Test
              </Button>
            </div>
          </Field>
        </div>
      </div>
    </Modal>
  );
}

/** Score bands used across the portfolio (same thresholds as scoreBand). */
type BandKey = 'healthy' | 'fair' | 'attention' | 'none';
const bandOf = (score: number | null): BandKey => (score === null ? 'none' : score >= 80 ? 'healthy' : score >= 65 ? 'fair' : 'attention');
const BAND_STYLE: Record<BandKey, { label: string; color: string; soft: string }> = {
  healthy: { label: 'Healthy', color: 'rgb(var(--good))', soft: 'bg-good-soft text-good' },
  fair: { label: 'Fair', color: 'rgb(var(--warn))', soft: 'bg-warn-soft text-warn' },
  attention: { label: 'Needs attention', color: 'rgb(var(--bad))', soft: 'bg-bad-soft text-bad' },
  none: { label: 'Not checked', color: 'rgb(var(--ink-subtle))', soft: 'bg-muted text-ink-muted' },
};
const SEV_DOT: Record<string, string> = { critical: 'bg-bad', high: 'bg-[#f97316]', medium: 'bg-warn', low: 'bg-ink-subtle' };

const initials = (name: string) =>
  name
    .replace(/\b(llc|inc|ltd|corp|co)\b\.?/gi, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('') || '?';

/** Filled trend line of the last checks, sized to its container. */
function TrendArea({ data, color }: { data: number[]; color: string }) {
  const w = 300;
  const h = 56;
  const min = Math.min(...data, 100);
  const max = Math.max(...data, 0);
  const lo = Math.max(0, Math.min(min, ...data) - 5);
  const hi = Math.min(100, Math.max(max, ...data) + 5);
  const pts = data.map((v, i) => [(i / Math.max(data.length - 1, 1)) * w, h - 4 - ((v - lo) / (hi - lo || 1)) * (h - 10)] as const);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const area = `${line} L${w},${h} L0,${h} Z`;
  const id = `trend-${color.replace(/[^a-z0-9]/gi, '')}`;
  const last = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-14 w-full" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <motion.path d={area} fill={`url(#${id})`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8 }} />
      <motion.path d={line} fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke"
        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, ease: 'easeOut' }} />
      <circle cx={last[0]} cy={last[1]} r={4} fill={color} stroke="rgb(var(--surface))" strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function OrgCard({ org, onSchedule }: { org: PortfolioOrg; onSchedule: () => void }) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const activate = useActivateOrg();
  const [disconnecting, setDisconnecting] = useState(false);
  const { canEdit, isAdmin } = useRole();
  const [reconnect, setReconnect] = useState(false);
  const connected = org.connectionStatus === 'connected';
  const delta = org.score !== null && org.previousScore !== null ? org.score - org.previousScore : null;
  const band = BAND_STYLE[bandOf(org.score)];
  const catScore = new Map(org.categoryScores.map((c) => [c.categoryId, c.score]));

  const open = (to: string) => {
    if (org.active) return navigate(to);
    activate.mutate(org.orgId, {
      onSuccess: () => {
        notify('Switched org', `You’re now working on ${org.organizationName}.`, 'success');
        navigate(to);
      },
      onError: (e) => notify('Couldn’t switch', errorMessage(e), 'warning'),
    });
  };

  return (
    <motion.div whileHover={{ y: -3 }} transition={{ type: 'spring', stiffness: 380, damping: 28 }}
      className={cx('card group relative flex h-full flex-col overflow-hidden', org.active && 'ring-2 ring-brand/40')}>
      <span className="absolute inset-x-0 top-0 h-1" style={{ background: band.color }} />
      <span className="pointer-events-none absolute -right-20 -top-20 h-48 w-48 rounded-full opacity-10 blur-3xl transition-opacity group-hover:opacity-20" style={{ background: band.color }} />

      {/* Identity */}
      <div className="relative flex items-start gap-3 p-5 pb-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-sm font-bold text-white shadow-sm"
          style={{ background: `linear-gradient(135deg, ${band.color}, rgb(var(--brand)))` }}>
          {initials(org.organizationName)}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="line-clamp-2 text-base font-semibold leading-snug" title={org.organizationName}>{org.organizationName}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
            {org.active && <Badge tone="brand">Active</Badge>}
            {org.running && <Badge tone="accent"><Loader2 className="mr-1 inline h-3 w-3 animate-spin" />Checking</Badge>}
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className={cx('h-1.5 w-1.5 rounded-full', connected ? 'bg-good' : 'bg-warn')} />
              <span className={connected ? 'text-ink-muted' : 'font-medium text-warn'}>
                {connected ? 'Connected' : org.connectionStatus === 'expired' ? 'Connection expired' : 'Not connected'}
              </span>
            </span>
            {org.edition && <span className="whitespace-nowrap text-ink-subtle">· {org.edition}{org.environment === 'sandbox' ? ' · Sandbox' : ''}</span>}
          </div>
        </div>
      </div>

      {/* Score + trend */}
      <div className="relative flex items-center gap-4 px-5 pb-4">
        <div className="flex shrink-0 flex-col items-center gap-1">
          <ScoreRing score={org.score} size={84} stroke={8} showBand={false} />
          <span className={cx('whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold', band.soft)}>{band.label}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-1 text-[11px]">
            <span className="font-medium text-ink-muted">Health trend</span>
            {delta !== null && delta !== 0 ? (
              <span className={cx('inline-flex items-center gap-0.5 whitespace-nowrap rounded-full px-1.5 py-0.5 font-semibold', delta > 0 ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
                {delta > 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
                {delta > 0 ? '+' : ''}{delta}
              </span>
            ) : delta === 0 ? <span className="text-ink-subtle">No change</span> : null}
          </div>
          {org.trend.length > 1 ? (
            <TrendArea data={org.trend} color={band.color} />
          ) : (
            <p className="flex h-14 items-center text-xs text-ink-subtle">Appears after the second check.</p>
          )}
          <p className="text-[11px] text-ink-subtle">{org.lastCheckedAt ? `Last checked ${fmtDate(org.lastCheckedAt)}` : 'Never checked'}</p>
        </div>
      </div>

      {/* Topic scores */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line px-5 py-4">
        {CATEGORIES.map((c) => {
          const s = catScore.get(c.id) ?? null;
          const b = BAND_STYLE[bandOf(s)];
          return (
            <div key={c.id} className="min-w-0">
              <div className="flex items-center gap-1.5 text-[11px]">
                <span style={{ color: CATEGORY_COLORS[c.id] }}><CategoryIcon id={c.id} className="h-3.5 w-3.5" /></span>
                <span className="min-w-0 flex-1 truncate text-ink-muted" title={c.name}>{c.shortName}</span>
                <span className="font-semibold tabular-nums">{s ?? '—'}</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                <motion.div className="h-full rounded-full" style={{ background: b.color }}
                  initial={{ width: 0 }} animate={{ width: `${s ?? 0}%` }} transition={{ duration: 0.8, ease: 'easeOut' }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Numbers */}
      <div className="grid grid-cols-3 divide-x divide-line border-y border-line bg-muted/30 text-center">
        <div className="px-2 py-3">
          <p className="text-lg font-semibold tabular-nums"><AnimatedNumber value={org.openProblems} /></p>
          <p className="text-[11px] text-ink-subtle">open problems</p>
        </div>
        <div className="px-2 py-3">
          <p className={cx('text-lg font-semibold tabular-nums', org.criticalProblems ? 'text-bad' : '')}><AnimatedNumber value={org.criticalProblems} /></p>
          <p className="text-[11px] text-ink-subtle">critical · {org.highProblems} high</p>
        </div>
        <div className="px-2 py-3" title="Value at risk on the biggest single problem (problems can overlap, so they aren’t added up)">
          <p className="text-lg font-semibold tabular-nums">{org.valueAtRisk ? fmtCompact(org.valueAtRisk) : '—'}</p>
          <p className="text-[11px] text-ink-subtle">biggest risk</p>
        </div>
      </div>

      {/* Fix first */}
      {org.topProblems.length > 0 && (
        <div className="px-5 pt-4">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">Fix first</p>
          <ul className="space-y-0.5">
            {org.topProblems.map((p) => (
              <li key={p.findingId}>
                <button
                  onClick={() => open(`/results?assessment=${encodeURIComponent(p.assessmentId)}&finding=${encodeURIComponent(p.findingId)}`)}
                  className="group/row -mx-2 flex w-[calc(100%+1rem)] items-center gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-muted"
                >
                  <span className={cx('h-2 w-2 shrink-0 rounded-full', SEV_DOT[p.severity] ?? 'bg-ink-subtle')} title={p.severity} />
                  <span className="min-w-0 flex-1 truncate group-hover/row:text-brand">{p.name}</span>
                  {p.affectedRecords > 0 && <span className="shrink-0 tabular-nums text-ink-subtle">{fmtNumber(p.affectedRecords)}</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex-1" />

      {/* Schedule + actions */}
      <div className="px-5 pt-4">
        <button onClick={onSchedule} disabled={!connected || !canEdit} title={canEdit ? undefined : 'View-only access'}
          className={cx('flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition disabled:opacity-50',
            org.schedule?.enabled ? 'bg-brand-soft text-brand-ink hover:brightness-95' : 'border border-dashed border-line text-ink-muted hover:border-brand hover:text-brand')}>
          <CalendarClock className="h-4 w-4 shrink-0" />
          {org.schedule?.enabled
            ? <span className="truncate">{FREQ_LABEL[org.schedule.frequency]} checks · next {org.schedule.nextRunAt ? fmtDate(org.schedule.nextRunAt) : '—'}{org.schedule.alertEmail ? ` · alerts to ${org.schedule.alertEmail}` : ''}</span>
            : org.schedule ? <span>Scheduled checks paused</span> : <span>Schedule automatic checks and alerts</span>}
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2 p-5 pt-3">
        {connected ? (
          <>
            <Button size="sm" variant="primary" icon={<LayoutDashboard className="h-3.5 w-3.5" />} onClick={() => open('/dashboard')} disabled={activate.isPending}>
              {org.active ? 'Open' : 'Switch & open'}
            </Button>
            {canEdit && (
              <Button size="sm" icon={<Play className="h-3.5 w-3.5" />} onClick={() => open('/assessment')} disabled={activate.isPending || org.running}>
                Run check
              </Button>
            )}
          </>
        ) : canEdit ? (
          <Button size="sm" variant="primary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => setReconnect(true)}>
            Reconnect
          </Button>
        ) : null}
        {isAdmin && org.connectionStatus === 'disconnected' && (
          <Button size="sm" variant="ghost" className="ml-auto" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setDisconnecting(true)}>
            Delete saved results
          </Button>
        )}
        {isAdmin && org.connectionStatus !== 'disconnected' && (
          <Button size="sm" variant="ghost" className="ml-auto" icon={<Trash2 className="h-3.5 w-3.5" />}
            onClick={() => setDisconnecting(true)}>
            Disconnect
          </Button>
        )}
      </div>
      <ConnectModal open={reconnect} onClose={() => setReconnect(false)} />
      <DisconnectDialog open={disconnecting} orgId={org.orgId} orgName={org.organizationName} deleteOnly={org.connectionStatus === 'disconnected'} onClose={() => setDisconnecting(false)} />
    </motion.div>
  );
}

/** Invites the next connection, so a small portfolio doesn't look empty. */
function AddOrgCard({ onClick, first }: { onClick: () => void; first?: boolean }) {
  return (
    <motion.button whileHover={{ y: -3 }} onClick={onClick}
      className="group flex h-full min-h-[320px] w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-line bg-surface/50 p-8 text-center transition hover:border-brand hover:bg-brand-soft/40">
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft text-brand transition group-hover:scale-110">
        <Plus className="h-7 w-7" />
      </span>
      <span className="text-base font-semibold">{first ? 'Connect your first client' : 'Add your next client'}</span>
      <span className="max-w-[260px] text-sm text-ink-muted">Connect another Salesforce org to track its health, trend and risks here. Read-only access.</span>
      <span className="mt-1 inline-flex items-center gap-1 text-sm font-semibold text-brand">Connect Salesforce <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
    </motion.button>
  );
}

/** Portfolio summary: average health, how clients spread across health bands, and headline numbers. */
function PortfolioHero({ orgs }: { orgs: PortfolioOrg[] }) {
  const scored = orgs.filter((o) => o.score !== null);
  const avg = scored.length ? Math.round(scored.reduce((a, o) => a + (o.score ?? 0), 0) / scored.length) : null;
  const counts: Record<BandKey, number> = { healthy: 0, fair: 0, attention: 0, none: 0 };
  orgs.forEach((o) => { counts[bandOf(o.score)] += 1; });
  const critical = orgs.reduce((a, o) => a + o.criticalProblems, 0);
  const open = orgs.reduce((a, o) => a + o.openProblems, 0);
  const biggest = orgs.reduce((m, o) => Math.max(m, o.valueAtRisk ?? 0), 0);
  const scheduled = orgs.filter((o) => o.schedule?.enabled).length;
  const stats = [
    { label: 'Open problems', value: <AnimatedNumber value={open} />, icon: <ListChecks className="h-4 w-4" />, tone: 'text-brand bg-brand-soft' },
    { label: 'Critical', value: <AnimatedNumber value={critical} />, icon: <BellRing className="h-4 w-4" />, tone: 'text-bad bg-bad-soft' },
    { label: 'Biggest single risk', value: biggest ? fmtCompact(biggest) : '—', icon: <CircleDollarSign className="h-4 w-4" />, tone: 'text-warn bg-warn-soft' },
    { label: 'On a schedule', value: `${scheduled} of ${orgs.length}`, icon: <CalendarClock className="h-4 w-4" />, tone: 'text-good bg-good-soft' },
  ];

  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="card relative mb-6 overflow-hidden bg-gradient-to-br from-brand-soft/70 via-surface to-surface p-6">
      <span className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-brand/10 blur-3xl" />
      <div className="relative grid items-center gap-6 lg:grid-cols-[auto,1fr,auto]">
        <div className="flex items-center gap-5">
          <ScoreRing score={avg} size={112} stroke={10} label="Average" showBand={false} />
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-brand">Portfolio health</p>
            <p className="mt-1 text-2xl font-semibold tracking-tight">
              {orgs.length} {orgs.length === 1 ? 'client org' : 'client orgs'}
            </p>
            <p className="text-sm text-ink-muted">{scored.length} checked · average score {avg ?? '—'}</p>
          </div>
        </div>

        <div className="min-w-0">
          <div className="flex h-3 overflow-hidden rounded-full bg-muted">
            {(['healthy', 'fair', 'attention', 'none'] as BandKey[]).map((k) =>
              counts[k] ? (
                <motion.div key={k} title={`${BAND_STYLE[k].label}: ${counts[k]}`} style={{ background: BAND_STYLE[k].color }}
                  initial={{ width: 0 }} animate={{ width: `${(counts[k] / orgs.length) * 100}%` }} transition={{ duration: 0.8 }} />
              ) : null,
            )}
          </div>
          <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {(['healthy', 'fair', 'attention', 'none'] as BandKey[]).map((k) => (
              <span key={k} className="inline-flex items-center gap-1.5 text-ink-muted">
                <span className="h-2 w-2 rounded-full" style={{ background: BAND_STYLE[k].color }} />
                {BAND_STYLE[k].label} <span className="font-semibold text-ink">{counts[k]}</span>
              </span>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2">
          {stats.map((s) => (
            <div key={s.label} className="flex items-center gap-2.5 rounded-xl bg-surface/80 px-3 py-2 shadow-sm ring-1 ring-line">
              <span className={cx('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', s.tone)}>{s.icon}</span>
              <span className="min-w-0">
                <span className="block text-base font-semibold leading-tight tabular-nums">{s.value}</span>
                <span className="block truncate text-[11px] text-ink-subtle">{s.label}</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </motion.section>
  );
}

type SortKey = 'attention' | 'name' | 'score' | 'checked';
type FilterKey = 'all' | 'attention' | 'healthy' | 'disconnected';

export default function PortfolioPage() {
  const q = usePortfolio();
  const { canEdit } = useRole();
  const [adding, setAdding] = useState(false);
  const [scheduling, setScheduling] = useState<PortfolioOrg | null>(null);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('attention');
  const [filter, setFilter] = useState<FilterKey>('all');
  const all = q.data ?? [];
  const orgs = useMemo(() => all.filter((o) => !o.hidden), [all]);
  const removed = all.filter((o) => o.hidden);
  const addBack = useActivateOrg();

  const shown = useMemo(() => {
    const term = search.trim().toLowerCase();
    const list = orgs.filter((o) => {
      if (term && !o.organizationName.toLowerCase().includes(term)) return false;
      if (filter === 'attention') return bandOf(o.score) === 'attention' || o.criticalProblems > 0;
      if (filter === 'healthy') return bandOf(o.score) === 'healthy';
      if (filter === 'disconnected') return o.connectionStatus !== 'connected';
      return true;
    });
    const by: Record<SortKey, (a: PortfolioOrg, b: PortfolioOrg) => number> = {
      attention: (a, b) => b.criticalProblems - a.criticalProblems || (a.score ?? 101) - (b.score ?? 101),
      name: (a, b) => a.organizationName.localeCompare(b.organizationName),
      score: (a, b) => (b.score ?? -1) - (a.score ?? -1),
      checked: (a, b) => (b.lastCheckedAt ?? '').localeCompare(a.lastCheckedAt ?? ''),
    };
    return [...list].sort(by[sort]);
  }, [orgs, search, filter, sort]);

  return (
    <div>
      <PageHeader
        title="Client portfolio"
        description="Every Salesforce org you look after: health, trend, risk and scheduled checks in one place."
        actions={canEdit ? <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setAdding(true)}>Connect another org</Button> : undefined}
      />
      {q.isLoading ? (
        <div className="card"><LoadingState rows={6} label="Loading your orgs…" /></div>
      ) : q.error ? (
        <div className="card"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>
      ) : orgs.length === 0 ? (
        canEdit ? (
          <div className="mx-auto max-w-md"><AddOrgCard first onClick={() => setAdding(true)} /></div>
        ) : (
          <div className="card">
            <EmptyState icon={<Building2 className="h-6 w-6" />} title="No orgs yet" description="Ask an admin to give you access to a client org." />
          </div>
        )
      ) : (
        <>
          <PortfolioHero orgs={orgs} />

          {orgs.length > 1 && (
            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
              <label className="relative sm:w-64">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
                <input className="input pl-9" placeholder="Find a client…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Find a client" />
              </label>
              <Segmented<FilterKey> layoutId="portfolio-filter" value={filter} onChange={setFilter}
                options={[{ id: 'all', label: 'All' }, { id: 'attention', label: 'Needs attention' }, { id: 'healthy', label: 'Healthy' }, { id: 'disconnected', label: 'Not connected' }]} />
              <Select<SortKey> label="Sort clients" value={sort} onChange={setSort} className="sm:ml-auto sm:w-56"
                options={[{ value: 'attention', label: 'Most urgent first' }, { value: 'score', label: 'Highest score first' }, { value: 'checked', label: 'Recently checked' }, { value: 'name', label: 'Name A–Z' }]} />
            </div>
          )}

          {shown.length === 0 ? (
            <div className="card"><EmptyState icon={<Search className="h-6 w-6" />} title="No clients match" description="Try another name or filter." /></div>
          ) : (
            <StaggerGrid className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {shown.map((o) => (
                <StaggerItem key={o.orgId} className="h-full">
                  <OrgCard org={o} onSchedule={() => setScheduling(o)} />
                </StaggerItem>
              ))}
              {canEdit && filter === 'all' && !search && (
                <StaggerItem className="h-full">
                  <AddOrgCard onClick={() => setAdding(true)} />
                </StaggerItem>
              )}
            </StaggerGrid>
          )}
        </>
      )}
      {removed.length > 0 && (
        <details className="card mt-6 px-5 py-3">
          <summary className="cursor-pointer text-sm font-medium text-ink-muted">Removed from your list ({removed.length})</summary>
          <ul className="mt-2 divide-y divide-line">
            {removed.map((o) => (
              <li key={o.orgId} className="flex items-center gap-3 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate">{o.organizationName}</span>
                <Button size="sm" disabled={addBack.isPending} onClick={() => addBack.mutate(o.orgId)}>Add back</Button>
              </li>
            ))}
          </ul>
        </details>
      )}
      <ConnectModal open={adding} onClose={() => setAdding(false)} />
      {scheduling && <ScheduleModal org={scheduling} onClose={() => setScheduling(null)} />}
    </div>
  );
}
