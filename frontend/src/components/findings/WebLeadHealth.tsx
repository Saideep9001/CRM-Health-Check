import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { CheckCircle2, CircleSlash, TrendingDown, XCircle } from 'lucide-react';
import { indicatorApi } from '@/api/endpoints';
import { cx, fmtNumber } from '@/lib/format';

/** YYYY-MM-DD in the viewer's own time zone (what a date input shows). */
const day = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return day(d);
};

/** The Web-to-Lead table's created-date period: any time, the last 7 or 14 days, the last month, or custom dates. `onChange`
 *  gets the API's `period`: undefined (any time), "7", "14", "30" or "range:YYYY-MM-DD:YYYY-MM-DD". */
export function CreatedPeriod({ onChange }: { onChange: (period: string | undefined) => void }) {
  const today = day(new Date());
  const [choice, setChoice] = useState('any');
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(today);
  const valid = (f: string, t: string) => !!f && !!t && f <= t && f <= today;
  const apply = (c: string, f = from, t = to) => {
    setChoice(c);
    if (c === 'custom' && !valid(f, t)) return; // keep the last good period until both dates make sense
    onChange(c === 'any' ? undefined : c === 'custom' ? `range:${f}:${t}` : c);
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
      <span>Created</span>
      <select className="input h-7 w-auto py-0 text-xs" value={choice} onChange={(e) => apply(e.target.value)} aria-label="Lead created date">
        <option value="any">Any time</option>
        <option value="7">Last 7 days</option>
        <option value="14">Last 14 days</option>
        <option value="30">Last 1 month</option>
        <option value="custom">Custom dates…</option>
      </select>
      {choice === 'custom' && (
        <>
          <span>from</span>
          <input
            type="date"
            className="input h-7 w-auto py-0 text-xs"
            value={from}
            max={to || today}
            onChange={(e) => {
              setFrom(e.target.value);
              apply('custom', e.target.value, to);
            }}
            aria-label="Created from"
          />
          <span>to</span>
          <input
            type="date"
            className="input h-7 w-auto py-0 text-xs"
            value={to}
            min={from || undefined}
            max={today}
            onChange={(e) => {
              setTo(e.target.value);
              apply('custom', from, e.target.value);
            }}
            aria-label="Created to"
          />
          {!valid(from, to) && <span className="text-bad">From must be on or before To</span>}
        </>
      )}
    </span>
  );
}

const TONES = {
  good: { box: 'border-good/40 bg-good-soft/40', badge: 'bg-good-soft text-good', icon: CheckCircle2, bar: 'bg-good' },
  warn: { box: 'border-warn/40 bg-warn-soft/40', badge: 'bg-warn-soft text-warn', icon: TrendingDown, bar: 'bg-warn' },
  bad: { box: 'border-bad/40 bg-bad-soft/40', badge: 'bg-bad-soft text-bad', icon: XCircle, bar: 'bg-bad' },
  muted: { box: 'border-line bg-muted/40', badge: 'bg-muted text-ink-muted', icon: CircleSlash, bar: 'bg-ink-subtle' },
} as const;

/** Bars for counts over time (oldest first), each labelled under it, with the count on hover and above the bar. */
function Bars({ title, items, bar, action }: { title: string; items: { label: string; count: number }[]; bar: string; action?: React.ReactNode }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">{title}</p>
        {action}
      </div>
      <div className="flex h-28 items-end gap-1">
        {items.map((i) => (
          <div key={i.label} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-0.5" title={`${i.label}: ${i.count}`}>
            <span className="text-[10px] tabular-nums text-ink-muted">{i.count || ''}</span>
            <div className={cx('w-full rounded-t', i.count ? bar : 'bg-line')} style={{ height: `${Math.max(2, (i.count / max) * 80)}px` }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1">
        {items.map((i) => (
          <span key={i.label} className="min-w-0 flex-1 truncate text-center text-[9px] text-ink-subtle" title={i.label}>
            {i.label.split(' – ')[0]}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Web-to-Lead health: whether website Leads are still arriving as usual (from their history), with the last 12 weeks and
 *  12 months of website Leads, read live from Salesforce. */
export function WebLeadHealth({ assessmentId, areaId }: { assessmentId: string; areaId: string }) {
  // the chart's calendar year (undefined = the last 12 months)
  const [year, setYear] = useState<number | undefined>();
  const data = useQuery({
    queryKey: ['web-lead-history', assessmentId, areaId, year],
    queryFn: ({ signal }) => indicatorApi.webLeadHistory(assessmentId, areaId, signal, year),
    staleTime: 60_000,
    placeholderData: (prev) => prev, // keep the chart while another year loads
  });
  if (data.isLoading) return <p className="text-sm text-ink-subtle">Reading the website Lead history from Salesforce…</p>;
  if (data.error) return <p className="rounded-lg bg-bad-soft/50 px-4 py-3 text-sm text-bad">Couldn’t read the website Lead history: {(data.error as Error).message}</p>;
  const h = data.data!;
  const t = TONES[h.tone];
  const Icon = t.icon;
  return (
    <div className={cx('space-y-4 rounded-xl border p-4', t.box)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold">
            Website Lead health
            <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', t.badge)}>
              <Icon className="h-3.5 w-3.5" /> {h.verdict}
            </span>
          </p>
          <p className="mt-1 text-xs text-ink-muted">{h.why}</p>
        </div>
        <div className="flex gap-4 text-xs">
          {[
            ['Last 7 days', fmtNumber(h.last7)],
            ['Last 14 days', fmtNumber(h.last14)],
            ['Usual in 14 days', fmtNumber(h.expected14)],
            ['Latest web lead', h.lastCreated ?? 'None'],
          ].map(([k, v]) => (
            <div key={k}>
              <p className="text-ink-subtle">{k}</p>
              <p className="font-semibold tabular-nums">{v}</p>
            </div>
          ))}
        </div>
      </div>
      <Bars
        title={year ? `Website Leads per month (${year})` : 'Website Leads per month (last 12 months)'}
        items={h.months}
        bar={t.bar}
        action={
          <select
            className="input h-7 w-auto py-0 text-xs"
            value={year ?? ''}
            onChange={(e) => setYear(e.target.value ? Number(e.target.value) : undefined)}
            aria-label="Year"
          >
            <option value="">Last 12 months</option>
            {(h.years ?? []).map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        }
      />
    </div>
  );
}
