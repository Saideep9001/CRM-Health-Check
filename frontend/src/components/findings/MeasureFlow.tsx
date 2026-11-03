import { ChevronRight } from 'lucide-react';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { InfoTip } from '@/components/ui/HelpTip';
import { AnimatedNumber } from '@/components/ui/Visuals';
import { cx, fmtNumber } from '@/lib/format';
import type { FieldCheckResult, Finding, IndicatorValue } from '@/types';

type Tone = 'plain' | 'warn' | 'bad' | 'good';
export type FlowStep = { label: string; value: number; hint: string; tone?: Tone; suffix?: string; tip?: string };

const BOX: Record<Tone, string> = {
  plain: 'border-line bg-muted/40',
  warn: 'border-warn/30 bg-warn-soft/40',
  bad: 'border-bad/30 bg-bad-soft/40',
  good: 'border-good/30 bg-good-soft/40',
};
const NUMBER: Record<Tone, string> = { plain: 'text-ink', warn: 'text-warn', bad: 'text-bad', good: 'text-good' };

/** What a step means, for its info tip (a step can bring its own `tip`; extra detail is added after this). */
function explain(label: string): string | null {
  if (/ checked$/.test(label) && !/^(Fields|Key fields|Values|Custom fields)/.test(label))
    return 'Every record of this object read live from Salesforce for this check (up to 20,000).';
  const rules: [RegExp, string][] = [
    [/^Duplicate records found/, 'Records that match at least one other record on the fields compared (each record counted once).'],
    [/^Duplicate groups/, 'A group is a set of records that match each other: one real customer (or deal) entered more than once. Keep one record per group, usually the most complete or most recently used one, and merge the others into it.'],
    [/^Extra copies to merge/, 'Duplicate records found minus the one record you keep in each group: the copies to merge away.'],
    [/^(Key fields|Fields) checked/, 'The fields that should be filled in on every record.'],
    [/^Values checked/, 'Every value looked at: each record’s value in each field checked.'],
    [/^Empty values/, 'Values left blank, counted per field (a record with two empty fields counts twice here).'],
    [/^Records missing/, 'Records with at least one of these fields empty, each record counted once.'],
    [/^Invalid values found/, 'Values that break the standardisation rules: wrong format, odd casing, or a different spelling of a common value.'],
    [/^Records with invalid data/, 'Records with at least one invalid value, each record counted once.'],
    [/^Fields on the object/, 'Every field Salesforce lists for this object, standard and custom.'],
    [/^Well used|^Look current|^Active|^With /, 'The ones that pass this check.'],
    [/^Rarely filled|^Hardly ever filled|^Never filled in/, 'How often the field is filled in, across all the records.'],
  ];
  return rules.find(([re]) => re.test(label))?.[1] ?? null;
}

/** Numbered steps from what was checked to what was found, left to right, each with an info tip (every flow in the app). */
export function FlowSteps({ steps }: { steps: FlowStep[] }) {
  const cols = ['', 'sm:grid-cols-1', 'sm:grid-cols-2', 'sm:grid-cols-3', 'sm:grid-cols-2 lg:grid-cols-4', 'sm:grid-cols-2 lg:grid-cols-5'][steps.length] ?? 'lg:grid-cols-5';
  return (
    <ol className={cx('grid gap-2', cols, steps.length === 1 && 'max-w-sm')}>
      {steps.map((st, i) => (
        <li key={st.label} className="relative flex">
          <div className={cx('flex w-full flex-col rounded-xl border px-4 py-3', BOX[st.tone ?? 'plain'])}>
            <span className="flex items-center gap-2 text-xs font-medium text-ink-muted">
              {steps.length > 1 && (
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface text-[11px] font-bold text-ink ring-1 ring-line">{i + 1}</span>
              )}
              {st.label}
              <InfoTip label={`About ${st.label}`}>{[explain(st.label), st.tip].filter(Boolean).join(' ') || st.hint}</InfoTip>
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
              : /^Campaign Association Gaps/i.test(v.label)
                ? ['In a Campaign', 'Not in any Campaign']
                : /^Stale Leads/i.test(v.label)
                  ? ['Moving forward', 'Stuck in the same status']
                  : [null, null];
  if (!fine || !bad) return null;
  return [
    { label: `${Cap} checked`, value: total, hint: 'Every record read from Salesforce' },
    { label: fine, value: total - n, hint: `${pctOf(total - n, total)} of all ${what}`, tone: 'good' },
    { label: bad, value: n, hint: `${pctOf(n, total)} of all ${what}`, tone: 'bad' },
  ];
}

/** The same steps from the latest Check fields run, for the fields ticked there (null = all of them). The last step is the
 *  records table's own count, so it also follows the column filters. Null when there's nothing to work from. */
export function liveFlowFor(
  kind: 'missing' | 'standardization',
  check: FieldCheckResult,
  ticked: string[] | null,
  tableTotal: number | null,
  filtered: boolean,
): FlowStep[] | null {
  const what = objectLabel(check.object).toLowerCase();
  const Cap = what.charAt(0).toUpperCase() + what.slice(1);
  const picked = check.fields.filter((f) => (ticked == null || ticked.includes(f.name)) && (kind === 'missing' || f.standardization));
  if (!picked.length) return null;
  const records = check.scanned;
  const last = filtered ? ' (matching your column filters)' : '';
  if (kind === 'missing') {
    const values = records * picked.length;
    const empty = picked.reduce((n, f) => n + f.empty, 0);
    const missing = tableTotal ?? (ticked == null ? (check.anyEmpty ?? 0) : Math.max(...picked.map((f) => f.empty)));
    return [
      { label: `${Cap} checked`, value: records, hint: check.truncated ? 'The first 20,000 read from Salesforce' : 'Every record read from Salesforce' },
      { label: 'Fields checked', value: picked.length, hint: picked.map((f) => f.label).join(', ') },
      { label: 'Values checked', value: values, hint: `${fmtNumber(records)} records × ${picked.length} field${picked.length > 1 ? 's' : ''}` },
      { label: 'Empty values', value: empty, hint: `${pctOf(empty, values)} of the values · ${fmtNumber(values - empty)} filled in`, tone: 'warn' },
      { label: 'Records missing a field', value: missing, hint: `${pctOf(missing, records)} of all ${what} miss at least one (each counted once)${last}`, tone: 'bad' },
    ];
  }
  const values = picked.reduce((n, f) => n + f.filled, 0);
  const odd = picked.reduce((n, f) => n + (f.standardization?.oddRecords ?? 0), 0);
  const worst = [...picked].sort((a, b) => (b.standardization?.oddRecords ?? 0) - (a.standardization?.oddRecords ?? 0)).filter((f) => f.standardization?.oddRecords).slice(0, 2);
  const bad = tableTotal ?? (ticked == null ? (check.anyOdd ?? odd) : odd);
  return [
    { label: `${Cap} checked`, value: records, hint: check.truncated ? 'The first 20,000 read from Salesforce' : 'Every record read from Salesforce' },
    { label: 'Values checked', value: values, hint: `Filled-in values of ${picked.length} field${picked.length > 1 ? 's' : ''} (${picked.map((f) => f.label).join(', ')})` },
    { label: 'Invalid values found', value: odd, hint: worst.length ? `Most in ${worst.map((f) => `${f.label} (${fmtNumber(f.standardization!.oddRecords)})`).join(', ')}` : 'Every value follows the rules', tone: 'warn' },
    { label: 'Records with invalid data', value: bad, hint: `${pctOf(bad, records)} of all ${what}; a record with several counts once${last}`, tone: 'bad' },
  ];
}

/** Area 2 (fields) cards: the steps from the fields looked at to the ones listed, from the card's own numbers. */
export function fieldFlowFor(v: IndicatorValue): FlowStep[] | null {
  const crit = (name: string) => (v.criteria ?? []).find(([k]) => k === name)?.[1] as string | undefined;
  const items = v.fieldList ?? [];
  const never = items.filter((f) => f.filled === 0).length;
  const n = v.value;
  const of = v.outOf ?? null;
  if (/^All Fields/.test(v.label)) {
    const m = crit('Fields')?.match(/([\d,]+) in all — ([\d,]+) standard, ([\d,]+) custom/);
    if (!m) return null;
    return [
      { label: 'Fields on the object', value: num(m[1]), hint: 'Every field Salesforce lists for it' },
      { label: 'From Salesforce', value: num(m[2]), hint: 'Standard fields' },
      { label: 'Added in your org', value: num(m[3]), hint: 'Custom fields (including installed packages)' },
      { label: 'Formula fields', value: num(crit('Formula fields')), hint: 'Worked out by Salesforce, never typed in' },
      { label: 'Required', value: num(crit('Required')), hint: 'Must be filled in to save a record' },
    ];
  }
  if (of == null) return null;
  if (/^Unused & Low-Completion Fields/.test(v.label)) {
    const hardly = items.filter((f) => /^Hardly ever/.test(f.note)).length;
    return [
      { label: 'Fields checked', value: of, hint: 'Standard and custom fields people fill in' },
      { label: 'Well used', value: of - n, hint: `Filled on 20% of records or more · ${pctOf(of - n, of)}`, tone: 'good' },
      { label: 'Rarely filled', value: n - hardly - never, hint: 'On 1% to under 20% of records', tone: 'warn' },
      { label: 'Hardly ever filled', value: hardly, hint: 'On fewer than 1% of records', tone: 'bad' },
      { label: 'Never filled in', value: never, hint: 'Empty on every record', tone: 'bad' },
    ];
  }
  if (/^Outdated Fields/.test(v.label))
    return [
      { label: 'Custom fields checked', value: of, hint: 'Built in your org' },
      { label: 'Look current', value: of - n, hint: pctOf(of - n, of), tone: 'good' },
      { label: 'Look outdated', value: n, hint: `Named old, backup, legacy, copy, test… · ${pctOf(n, of)}`, tone: 'bad' },
    ];
  if (/^Look-alike Fields/.test(v.label)) {
    const m = crit('Fields compared')?.match(/([\d,]+) fields, ([\d,]+) of them/);
    return [
      ...(m ? [{ label: 'Fields compared', value: num(m[1]), hint: 'Parts of addresses and map locations left out' }] : []),
      { label: 'Built in your org', value: of, hint: 'Each pair has at least one of these' },
      { label: 'Look-alike pairs', value: n, hint: 'Fields that seem to hold the same thing', tone: 'bad' },
      { label: 'Fields in a pair', value: items.length, hint: 'Listed below with the field they look like', tone: 'warn' },
    ];
  }
  if (/^Empty Fields Others Depend On/.test(v.label))
    return [
      { label: 'Nearly empty custom fields', value: of, hint: 'Filled on fewer than 20% of records' },
      { label: 'Nothing relies on them', value: of - n, hint: 'Safe to tidy up', tone: 'good' },
      { label: 'Relied on', value: n, hint: 'Used by a formula, validation rule, flow, report…', tone: 'bad' },
    ];
  return null;
}

/** The same steps for one record type: only the fields on its page layout (`fields`), counted the way the card counts
 *  (`fillable` = fields people fill in, `ownCustom` = custom fields built in the org). */
export function fieldFlowForRecordType(
  v: IndicatorValue,
  scope: { name: string; fields: Set<string>; fillable: Set<string>; ownCustom: Set<string> },
): FlowStep[] | null {
  const items = (v.fieldList ?? []).filter((f) => scope.fields.has(f.name));
  const n = items.length;
  const never = items.filter((f) => f.filled === 0).length;
  const inScope = (set: Set<string>) => [...scope.fields].filter((f) => set.has(f)).length;
  const on = `on ${scope.name}`;
  if (/^All Fields/.test(v.label)) {
    const custom = items.filter((f) => f.custom).length;
    return [
      { label: `Fields ${on}`, value: n, hint: 'On its page layout' },
      { label: 'From Salesforce', value: n - custom, hint: 'Standard fields' },
      { label: 'Added in your org', value: custom, hint: 'Custom fields' },
    ];
  }
  if (/^Unused & Low-Completion Fields/.test(v.label)) {
    const checked = inScope(scope.fillable);
    const hardly = items.filter((f) => /^Hardly ever/.test(f.note)).length;
    return [
      { label: 'Fields checked', value: checked, hint: `Fields people fill in, ${on}` },
      { label: 'Well used', value: Math.max(checked - n, 0), hint: `Filled on 20%+ · ${pctOf(Math.max(checked - n, 0), checked)}`, tone: 'good' },
      { label: 'Rarely filled', value: n - hardly - never, hint: 'On 1% to under 20% of records', tone: 'warn' },
      { label: 'Hardly ever filled', value: hardly, hint: 'On fewer than 1% of records', tone: 'bad' },
      { label: 'Never filled in', value: never, hint: 'Empty on every record', tone: 'bad' },
    ];
  }
  if (/^Outdated Fields/.test(v.label)) {
    const checked = inScope(scope.ownCustom);
    return [
      { label: 'Custom fields checked', value: checked, hint: `Built in your org, ${on}` },
      { label: 'Look current', value: Math.max(checked - n, 0), hint: pctOf(Math.max(checked - n, 0), checked), tone: 'good' },
      { label: 'Look outdated', value: n, hint: 'Named old, backup, legacy, copy, test…', tone: 'bad' },
    ];
  }
  if (/^Look-alike Fields/.test(v.label))
    return [
      { label: `Fields ${on}`, value: scope.fields.size, hint: 'On its page layout' },
      { label: 'Built in your org', value: inScope(scope.ownCustom), hint: 'Each pair has at least one of these' },
      { label: 'Fields in a look-alike pair', value: n, hint: 'Listed below with the field they look like', tone: 'bad' },
    ];
  if (/^Empty Fields Others Depend On/.test(v.label))
    return [
      { label: 'Custom fields checked', value: inScope(scope.ownCustom), hint: `Built in your org, ${on}` },
      { label: 'Nearly empty and relied on', value: n, hint: 'Used by a formula, validation rule, flow, report…', tone: 'bad' },
    ];
  return null;
}
