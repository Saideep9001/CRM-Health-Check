import { ChevronRight } from 'lucide-react';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { AnimatedNumber } from '@/components/ui/Visuals';
import { cx, fmtNumber } from '@/lib/format';
import type { Finding, IndicatorValue } from '@/types';

type Tone = 'plain' | 'warn' | 'bad' | 'good';
export type FlowStep = { label: string; value: number; hint: string; tone?: Tone; suffix?: string };

const BOX: Record<Tone, string> = {
  plain: 'border-line bg-muted/40',
  warn: 'border-warn/30 bg-warn-soft/40',
  bad: 'border-bad/30 bg-bad-soft/40',
  good: 'border-good/30 bg-good-soft/40',
};
const NUMBER: Record<Tone, string> = { plain: 'text-ink', warn: 'text-warn', bad: 'text-bad', good: 'text-good' };

/** Numbered steps from what was checked to what was found, left to right (the duplicates flow, for any card). */
export function FlowSteps({ steps }: { steps: FlowStep[] }) {
  const cols = ['', 'sm:grid-cols-1', 'sm:grid-cols-2', 'sm:grid-cols-3', 'sm:grid-cols-2 lg:grid-cols-4', 'sm:grid-cols-2 lg:grid-cols-5'][steps.length] ?? 'lg:grid-cols-5';
  return (
    <ol className={cx('grid gap-2', cols)}>
      {steps.map((st, i) => (
        <li key={st.label} className="relative flex">
          <div className={cx('flex w-full flex-col rounded-xl border px-4 py-3', BOX[st.tone ?? 'plain'])}>
            <span className="flex items-center gap-2 text-xs font-medium text-ink-muted">
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface text-[11px] font-bold text-ink ring-1 ring-line">{i + 1}</span>
              {st.label}
            </span>
            <span className={cx('mt-1.5 text-2xl font-semibold tabular-nums tracking-tight', NUMBER[st.tone ?? 'plain'])}>
              <AnimatedNumber value={st.value} />
              {st.suffix ?? ''}
            </span>
            <span className="mt-0.5 text-[11px] leading-snug text-ink-muted">{st.hint}</span>
          </div>
          {i < steps.length - 1 && (
            <ChevronRight className="absolute -right-2.5 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 rounded-full bg-surface text-ink-subtle ring-1 ring-line lg:block" aria-hidden="true" />
          )}
        </li>
      ))}
    </ol>
  );
}

const num = (s: string | undefined | null) => (s ? Number((s.match(/[\d,]+(\.\d+)?/)?.[0] ?? '').replace(/,/g, '')) || 0 : 0);
const pctOf = (n: number, of: number) => (of ? `${Math.round((100 * n) / of)}%` : '—');

/** The steps behind an Area 1 card's number, worked out from what the health check saved (its rules and per-field counts). */
export function flowFor(v: IndicatorValue, finding?: Finding | null): FlowStep[] | null {
  const crit = (name: string) => (v.criteria ?? []).find(([k]) => k === name)?.[1] as string | undefined;
  const checked = num(crit('Records checked'));
  const what = (v.recordObjects?.[0] ? objectLabel(v.recordObjects[0]) : (v.label.match(/\(([^)]+)\)$/)?.[1] ?? 'records')).toLowerCase();
  const Cap = what.charAt(0).toUpperCase() + what.slice(1);
  const fs = v.fieldScores ?? [];

  if (/^Duplicate/i.test(v.label)) {
    const m = crit("What's counted")?.match(/([\d,]+) in ([\d,]+) groups/);
    if (!m || !checked) return null;
    const extra = num(m[1]);
    const groups = num(m[2]);
    const found = extra + groups;
    return [
      { label: `${Cap} checked`, value: checked, hint: 'Every record read from Salesforce' },
      { label: 'Duplicate records found', value: found, hint: `${pctOf(found, checked)} of all ${what} match at least one other`, tone: 'warn' },
      { label: 'Duplicate groups', value: groups, hint: 'Sets of records that match each other' },
      { label: 'Keep one per group', value: groups, hint: 'The record you keep in each group', tone: 'good' },
      { label: 'Extra copies to merge', value: extra, hint: `${fmtNumber(found)} found − ${fmtNumber(groups)} kept · ${pctOf(extra, checked)} of all ${what}`, tone: 'bad' },
    ];
  }
  if (/^Missing/i.test(v.label) && fs.length) {
    const records = fs[0].of;
    const values = fs.reduce((n, f) => n + f.of, 0);
    const empty = fs.reduce((n, f) => n + f.count, 0);
    const missing = finding?.affectedRecords ?? (v.unit === '%' ? Math.round((v.value * records) / 100) : 0);
    return [
      { label: `${Cap} checked`, value: records, hint: 'Every record read from Salesforce' },
      { label: 'Key fields checked', value: fs.length, hint: fs.map((f) => f.label).join(', ') },
      { label: 'Values checked', value: values, hint: `${fmtNumber(records)} records × ${fs.length} key fields` },
      { label: 'Empty values', value: empty, hint: `${pctOf(empty, values)} of the values · ${fmtNumber(values - empty)} filled in`, tone: 'warn' },
      { label: 'Records missing a key field', value: missing, hint: `${pctOf(missing, records)} of all ${what} miss at least one (each counted once)`, tone: 'bad' },
    ];
  }
  if (/^Data Standardi/i.test(v.label) && fs.length) {
    const values = fs.reduce((n, f) => n + f.of, 0);
    const odd = fs.reduce((n, f) => n + f.count, 0);
    const worst = [...fs].sort((a, b) => b.count - a.count).filter((f) => f.count).slice(0, 2);
    return [
      ...(checked ? [{ label: `${Cap} checked`, value: checked, hint: 'Every record read from Salesforce' }] : []),
      { label: 'Values checked', value: values, hint: `Filled-in values of ${fs.length} fields (${fs.map((f) => f.label).join(', ')})` },
      { label: 'Invalid values found', value: odd, hint: worst.length ? `Most in ${worst.map((f) => `${f.label} (${fmtNumber(f.count)})`).join(', ')}` : 'Every value follows the rules', tone: 'warn' },
      { label: 'Records with invalid data', value: v.value, hint: `${checked ? `${pctOf(v.value, checked)} of all ${what}; ` : ''}a record with several counts once`, tone: 'bad' },
    ];
  }
  // "n of total …" cards: No Activity in 6 Months, Accounts Without Contacts / Open Opportunities
  const counted = crit("What's counted")?.match(/([\d,]+) of ([\d,]+)/);
  if (!counted) return null;
  const n = num(counted[1]);
  const total = num(counted[2]);
  const [fine, bad] = /^No Activity/i.test(v.label)
    ? ['Active in the last 6 months', 'No activity in 6 months']
    : /Without Contacts/i.test(v.label)
      ? ['With at least one Contact', 'Without Contacts']
      : /Without Open Opportunities/i.test(v.label)
        ? ['With an open Opportunity', 'Without an open Opportunity']
        : /^Closed Lost Without a Reason/i.test(v.label)
          ? ['Lost with a reason', 'Lost with no reason']
          : /Without Line Items/i.test(v.label)
            ? ['With line items', 'Without line items']
            : /Without Contact Roles/i.test(v.label)
              ? ['With a Contact Role', 'Without a Contact Role']
              : [null, null];
  if (!fine || !bad) return null;
  return [
    { label: `${Cap} checked`, value: total, hint: 'Every record read from Salesforce' },
    { label: fine, value: total - n, hint: `${pctOf(total - n, total)} of all ${what}`, tone: 'good' },
    { label: bad, value: n, hint: `${pctOf(n, total)} of all ${what}`, tone: 'bad' },
  ];
}
