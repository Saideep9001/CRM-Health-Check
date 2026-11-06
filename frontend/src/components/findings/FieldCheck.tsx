import { RecordLink, useOpenRecord } from '@/components/data/RecordLink';
import { AlertTriangle, ChevronDown, ListChecks, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { errorMessage } from '@/api/client';
import { useCheckFields, useEmptyOptions } from '@/api/queries';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { cx, fmtNumber } from '@/lib/format';
import type { FieldCheckField, FieldCheckResult } from '@/types';
import { Button } from '../ui/Button';
import { LoadingState } from '../ui/States';
import { DuplicateResults, show, type FinderKind } from './DuplicateFinder';
import { EmptyRecords, fieldsNamed } from './EmptyFieldsFinder';
import { useExpand } from '@/components/ui/Expand';

const MAX_FIELDS = 10;
export const ALL = '__all__'; // the "all chosen fields together" row

type Pick = { field: string; kind: FinderKind };

/** How the chosen fields count as duplicates: AND = records matching on all of them (common duplicates only), OR = each
 *  field's own duplicates, CUSTOM = a condition over the numbered fields, e.g. 1 AND (2 OR 3). */
export type MatchMode = 'AND' | 'OR' | 'CUSTOM';
const MODES: { value: MatchMode; label: string; help: string }[] = [
  { value: 'AND', label: 'AND', help: 'Only records that are duplicates on every chosen field together (common duplicates).' },
  { value: 'OR', label: 'OR', help: 'Each field’s own duplicates, field by field.' },
  { value: 'CUSTOM', label: 'Custom', help: 'Your own condition over the numbered fields, e.g. 1 AND (2 OR 3).' },
];
const MAX_GROUPS = 5; // OR'd groups the check takes
const MAX_GROUP_FIELDS = 6; // fields in one AND group

/** A condition like "1 AND (2 OR 3)" over the numbered fields, as OR'd groups of AND'd fields
 *  ([[1, 2], [1, 3]]), or an error in plain words. */
export function parseLogic(text: string, n: number): { groups: number[][] } | { error: string } {
  const tokens = text.toUpperCase().match(/\d+|AND|OR|\(|\)|\S+/g) ?? [];
  let i = 0;
  const fail = (error: string) => ({ error });
  type R = number[][] | { error: string };
  const isErr = (r: R): r is { error: string } => !Array.isArray(r);
  const expr = (): R => {
    let left = term();
    while (!isErr(left) && tokens[i] === 'OR') {
      i++;
      const right = term();
      if (isErr(right)) return right;
      left = [...left, ...right];
    }
    return left;
  };
  const term = (): R => {
    let left = factor();
    while (!isErr(left) && tokens[i] === 'AND') {
      i++;
      const right = factor();
      if (isErr(right)) return right;
      const l = left;
      left = l.flatMap((a) => right.map((b) => [...new Set([...a, ...b])]));
    }
    return left;
  };
  const factor = (): R => {
    const t = tokens[i++];
    if (t === undefined) return fail('The condition ends too soon.');
    if (t === '(') {
      const inner = expr();
      if (isErr(inner)) return inner;
      if (tokens[i++] !== ')') return fail('A bracket isn’t closed.');
      return inner;
    }
    if (/^\d+$/.test(t)) {
      const k = Number(t);
      return k >= 1 && k <= n ? [[k]] : fail(`There’s no field ${k}: use 1 to ${n}.`);
    }
    return fail(`“${t}” isn’t understood: use field numbers, AND, OR and brackets.`);
  };
  if (!tokens.length) return fail('Write a condition, e.g. 1 AND (2 OR 3).');
  const out = expr();
  if (isErr(out)) return out;
  if (i < tokens.length) return fail(`“${tokens[i]}” is out of place.`);
  const groups = out.map((g) => [...g].sort((a, b) => a - b)).filter((g, k, all) => all.findIndex((x) => x.join() === g.join()) === k);
  if (groups.length > MAX_GROUPS) return fail(`That makes ${groups.length} OR groups; use up to ${MAX_GROUPS}.`);
  if (groups.some((g) => g.length > MAX_GROUP_FIELDS)) return fail(`An AND group can have up to ${MAX_GROUP_FIELDS} fields.`);
  return { groups };
}
const allAnd = (n: number) => Array.from({ length: n }, (_, k) => k + 1).join(' AND ');
/** "Name AND Email OR Phone" */
export const ruleText = (rules: string[][]) => rules.map((g) => g.join(' AND ')).join(' OR ');

type Field = { name: string; label: string; type: string };
/** Ready-made duplicate checks for an object; a rule whose fields the org doesn't have is shown greyed out. */
const RULE_PRESETS: Record<string, { label: string; help: string; fields: (fs: Field[]) => (string | undefined)[] }[]> = {
  Account: [
    { label: 'Account Name', help: 'Accounts with the same name (fuzzy: Inc, Ltd, abbreviations and typos ignored).', fields: () => ['Name'] },
    { label: 'Account Name + Email', help: 'The same name AND the same email (the Account’s first email field).', fields: (fs) => ['Name', fs.find((f) => f.type === 'email')?.name] },
    {
      label: 'Account Name + Billing Address',
      help: 'The same name AND the same billing street, city, state, postal code and country.',
      fields: () => ['Name', 'BillingStreet', 'BillingCity', 'BillingState', 'BillingPostalCode', 'BillingCountry'],
    },
  ],
  Contact: [
    { label: 'Name', help: 'The same first AND last name.', fields: () => ['FirstName', 'LastName'] },
    { label: 'Name + Email', help: 'The same first name, last name AND email.', fields: () => ['FirstName', 'LastName', 'Email'] },
    { label: 'Name + Account Name', help: 'The same first name, last name AND Account.', fields: () => ['FirstName', 'LastName', 'Account.Name'] },
    {
      label: 'Name + Mailing Address',
      help: 'The same first name, last name AND mailing street, city, postal code and country.',
      fields: () => ['FirstName', 'LastName', 'MailingStreet', 'MailingCity', 'MailingPostalCode', 'MailingCountry'],
    },
  ],
  Lead: [
    { label: 'Name', help: 'The same first AND last name.', fields: () => ['FirstName', 'LastName'] },
    { label: 'Name + Email', help: 'The same first name, last name AND email.', fields: () => ['FirstName', 'LastName', 'Email'] },
    { label: 'Name + Company', help: 'The same first name, last name AND company.', fields: () => ['FirstName', 'LastName', 'Company'] },
    {
      label: 'Name + Address',
      help: 'The same first name, last name AND street, city, postal code and country.',
      fields: () => ['FirstName', 'LastName', 'Street', 'City', 'PostalCode', 'Country'],
    },
  ],
};

/** Invalid values of one field (the health check's Data Standardization rules), with why each one is flagged. */
function SpellingResults({ field, object }: { field: FieldCheckField; object: string }) {
  const openRecord = useOpenRecord();
  const ex = useExpand();
  const std = field.standardization!;
  const [query, setQuery] = useState('');
  const [reason, setReason] = useState<string | null>(null);
  const term = query.trim().toLowerCase();
  const rows = std.records.filter(
    (r) => (!reason || r.note === reason) && (!term || [...Object.values(r.values), r.note].some((v) => show(v).toLowerCase().includes(term))),
  );
  if (!std.oddRecords) return <p className="rounded-lg bg-good-soft/50 px-4 py-6 text-center text-sm text-good">Every value of {field.label} follows the rules.</p>;
  const reasons = std.reasons ?? [];
  return (
    <div className="space-y-3">
      {std.rule && (
        <p className="text-xs text-ink-muted">
          <span className="font-semibold text-ink">Counts as invalid:</span> {std.rule}
        </p>
      )}
      {reasons.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {reasons.map((x) => (
            <button
              key={x.reason}
              type="button"
              onClick={() => setReason(reason === x.reason ? null : x.reason)}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition',
                reason === x.reason ? 'border-bad bg-bad-soft text-bad' : 'border-line hover:border-bad/40 hover:bg-bad-soft/40',
              )}
              title={reason === x.reason ? 'Show every reason' : 'Show only these records'}
            >
              <AlertTriangle className="h-3 w-3 text-bad" />
              {x.reason}
              <span className="font-semibold tabular-nums">{fmtNumber(x.count)}</span>
            </button>
          ))}
        </div>
      )}
      {reasons.length === 0 && (
      <p className="text-xs text-ink-muted">
        Values are the same once upper/lower case, punctuation and spaces are ignored (countries and US states also match their codes: “USA” = “United States”,
        “California” = “CA”). The most common spelling is treated as right; every record using another spelling counts.
      </p>
      )}
      <div className="scrollbar-thin grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
        {std.variants.map((v) => (
          <div key={v.usual} className="rounded-lg border border-line px-3 py-2 text-xs">
            <p className="mb-1 font-semibold text-ink">
              {v.usual} <span className="font-normal text-ink-subtle">· {fmtNumber(v.oddRecords)} to fix</span>
            </p>
            <ul className="space-y-0.5">
              {v.spellings.map((sp, i) => (
                <li key={sp.value} className="flex justify-between gap-2">
                  <span className={cx('truncate', i === 0 ? 'text-good' : 'text-warn')}>“{sp.value}”</span>
                  <span className="tabular-nums text-ink-muted">{fmtNumber(sp.count)}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {reasons.length === 0 && std.variants.length < std.valuesWithVariants && <p className="text-[11px] text-ink-subtle">Showing {std.variants.length} of {fmtNumber(std.valuesWithVariants)} values.</p>}

      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
          <input className="input h-9 pl-8 text-sm" placeholder="Filter records by any value…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {ex.button}
      </div>
      {ex.wrap(
      <div className={cx(ex.scrollClass('max-h-[28rem]'), 'rounded-xl border border-line')}>
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
            <tr>
              {std.columns.map((c) => (
                <th key={c.name} className={cx('whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide', c.name === field.name ? 'bg-warn-soft/50 text-warn' : 'text-ink-subtle')}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r, ri) => (
              <tr key={r.id ?? ri} onClick={openRecord(object, r.id).onClick} className={cx('hover:bg-muted/60', openRecord(object, r.id).className)}>
                {std.columns.map((c, ci) => (
                  <td key={c.name} className={cx('max-w-[16rem] truncate px-3 py-2', c.name === field.name && r.note && 'bg-bad-soft/60')} title={c.name === field.name && r.note ? `${show(r.values[c.name])}
Why it’s flagged: ${r.note}` : show(r.values[c.name])}>
                    {ci === 0 && r.id ? (
                      <RecordLink object={object} id={r.id}>{show(r.values[c.name])}</RecordLink>
                    ) : (
                      <span className={c.name === field.name ? 'font-medium text-warn' : show(r.values[c.name]) === '—' ? 'text-ink-subtle' : ''}>{show(r.values[c.name])}</span>
                    )}
                    {c.name === field.name && r.note && (
                      <span className="mt-0.5 flex min-w-[11rem] items-start gap-1 whitespace-normal text-[10.5px] font-medium leading-snug text-bad">
                        <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
                        {r.note}
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
      )}
      {reason && <p className="text-[11px] text-ink-subtle">Showing only “{reason}”.</p>}
      {std.records.length < std.oddRecords && <p className="text-[11px] text-ink-subtle">Showing the first {fmtNumber(std.records.length)} of {fmtNumber(std.oddRecords)} records.</p>}
    </div>
  );
}

function Cell({ on, onClick, value, hint, tone, none, tick }: { on: boolean; onClick?: () => void; value?: number; hint?: string; tone: string; none?: string; tick?: boolean }) {
  if (value === undefined) return <td className="px-3 py-2 text-ink-subtle" title={none}>—</td>;
  return (
    <td className="px-1.5 py-1.5">
      <button
        type="button"
        onClick={onClick}
        className={cx('w-full rounded-lg border px-2.5 py-1.5 text-left transition', on ? 'border-brand bg-brand-soft/60' : 'border-transparent hover:border-brand/30 hover:bg-muted/60')}
      >
        {tick ? (
          // picks the field in the records table: a tick box beside the number, all on one line
          <span className="flex items-center gap-2">
            <span
              role="checkbox"
              aria-checked={on}
              className={cx('grid h-4 w-4 shrink-0 place-items-center rounded border text-[10px] leading-none', on ? 'border-brand bg-brand text-white' : 'border-ink-subtle/60 bg-surface')}
            >
              {on ? '✓' : ''}
            </span>
            <span className={cx('text-sm font-semibold tabular-nums', value ? tone : 'text-good')}>{fmtNumber(value)}</span>
            {hint && <span className="text-[11px] text-ink-muted">{hint}</span>}
          </span>
        ) : (
          <>
            <span className={cx('block text-sm font-semibold tabular-nums', value ? tone : 'text-good')}>{fmtNumber(value)}</span>
            {hint && <span className="block text-[11px] text-ink-muted">{hint}</span>}
          </>
        )}
      </button>
    </td>
  );
}

/** Pick fields of an object; for each one see its empty records, duplicates and inconsistent spellings — and, with several
 *  fields, records that are duplicates on all of them together. Only the objects the health check looked at. */
export function FieldCheck({
  objects,
  initialObject,
  focus,
  fieldsText = '',
  onResult,
  shownFields,
  onPickFields,
  recordFields = [],
  onLiveResult,
}: {
  objects: string[];
  initialObject?: string | null;
  focus?: FinderKind | null;
  fieldsText?: string;
  /** Tells the page about the latest run (null when it's reset), so its chart can follow the chosen fields. */
  onResult?: (result: FieldCheckResult | null) => void;
  /** Fields picked to show in the page's records table (its field selector); a number here picks its field there. */
  /** null = every field ticked (the default). */
  shownFields?: string[] | null;
  onPickFields?: (fields: string[] | null) => void;
  /** Fields the page's records table can narrow to for invalid data (empty values work for any field). */
  recordFields?: string[];
  /** Every run's result (also the one that runs on its own), for the page's records table (duplicate groups). */
  onLiveResult?: (result: FieldCheckResult | null) => void;
}) {
  // On a duplicates / missing / spelling page, only that page's column is shown.
  const shows = (k: FinderKind) => !focus || focus === k;
  const choices = useMemo(() => Array.from(new Set([...(initialObject ? [initialObject] : []), ...objects])), [objects, initialObject]);
  const [object, setObject] = useState(initialObject ?? choices[0]);
  const options = useEmptyOptions(object);
  const [chosen, setChosen] = useState<string[]>([]);
  const [mode, setMode] = useState<MatchMode>('AND');
  const [logic, setLogic] = useState('');
  const [ranMode, setRanMode] = useState<MatchMode>('AND'); // the mode of the result shown
  const [fieldQuery, setFieldQuery] = useState('');
  const [listOpen, setListOpen] = useState(true);
  const [pick, setPick] = useState<Pick | null>(null);
  const run = useCheckFields();
  const fields = options.data ?? [];

  useEffect(() => {
    if (initialObject) setObject(initialObject);
  }, [initialObject]);
  // Start from the fields the check looked at (e.g. Email for "without an email").
  useEffect(() => {
    const named = fieldsNamed(fieldsText, object, fields, MAX_FIELDS);
    setChosen(named);
    setMode('AND');
    setLogic('');
    setListOpen(named.length === 0); // fields already picked: keep the list folded
    setFieldQuery('');
    setPick(null);
    run.reset();
    onResult?.(null);
    onLiveResult?.(null);
    // The page's own fields are checked straight away, so the numbers show without a click (the page keeps the health check's own
    // chart until someone runs it themselves).
    if (named.length && options.data) runWith(named, false, 'AND');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [object, fieldsText, options.data]);

  // The chosen fields first, in the order they were picked, so they're seen without scrolling.
  const fieldList = [...chosen.flatMap((n) => fields.filter((f) => f.name === n)), ...fields.filter((f) => !chosen.includes(f.name))].filter(
    (f) => !fieldQuery || `${f.label} ${f.name}`.toLowerCase().includes(fieldQuery.toLowerCase()),
  );
  const label = (name: string) => fields.find((f) => f.name === name)?.label ?? name;
  const what = objectLabel(object).toLowerCase();

  /** The rule sent with the check: AND = all fields as one group, OR = no rule (each field on its own), CUSTOM = the condition. */
  const rulesFor = (names: string[], how: MatchMode): string[][] | undefined => {
    if (how === 'OR') return [];
    if (how === 'CUSTOM') {
      const parsed = parseLogic(logic, names.length);
      return 'groups' in parsed ? parsed.groups.map((g) => g.map((k) => names[k - 1])) : undefined;
    }
    return [names.slice(0, MAX_GROUP_FIELDS)];
  };
  function runWith(fieldNames: string[], tellPage: boolean, how: MatchMode = mode) {
    setListOpen(false);
    run.mutate(
      { object, fields: fieldNames, rules: rulesFor(fieldNames, how) },
      {
        onSuccess: (r: FieldCheckResult) => {
          setRanMode(how);
          if (tellPage) onResult?.(r);
          onLiveResult?.(r);
          // the page's records table shows what was asked: the common duplicates (AND / Custom) or each field's own (OR)
          if (focus === 'duplicates' && onPickFields) {
            if (how !== 'OR' && r.combined) onPickFields([ALL]);
            else onPickFields(r.fields.filter((f) => f.duplicates).map((f) => f.name));
          }
          const kind = focus ?? 'empty';
          // open the field with the most to look at for this page (e.g. Account Phone's odd values)
          const count = (f: FieldCheckField) => (kind === 'empty' ? f.empty : kind === 'duplicates' ? (f.duplicates?.extraCopies ?? 0) : (f.standardization?.oddRecords ?? 0));
          const most = [...r.fields].sort((a, b) => count(b) - count(a))[0];
          setPick({ field: kind === 'duplicates' && r.combined?.extraCopies ? ALL : (most ?? r.fields[0]).name, kind });
        },
      },
    );
  }
  const start = () => runWith(chosen, true);
  const presets = (RULE_PRESETS[object] ?? []).map((p) => {
    const names = p.fields(fields);
    const missing = names.some((n) => !n || !fields.some((f) => f.name === n));
    return { ...p, names: names as string[], missing };
  });
  const applyPreset = (names: string[]) => {
    setChosen(names);
    setMode('AND');
    runWith(names, true, 'AND');
  };
  const andOr = shows('duplicates') && chosen.length > 1;
  const pickMode = (m: MatchMode, rerun = false) => {
    setMode(m);
    if (m === 'CUSTOM' && !logic.trim()) setLogic(allAnd(chosen.length));
    if (rerun && m !== 'CUSTOM') runWith(chosen, true, m); // Custom runs once the condition is applied
  };
  const parsed = mode === 'CUSTOM' && andOr ? parseLogic(logic, chosen.length) : null;
  const logicError = parsed && 'error' in parsed ? parsed.error : null;

  const result = run.data;
  const picked = result && pick ? (pick.field === ALL ? null : result.fields.find((f) => f.name === pick.field)) : null;
  // Empty values and invalid data are shown in the page's records table (one table), not in a second one here.
  // Duplicates too: the ticked fields' groups replace the records table's (one table on the page).
  // AND / Custom: only the common duplicates (the rule's row); OR: each field's own duplicates.
  const commonOnly = shows('duplicates') && ranMode !== 'OR' && !!result?.combined;
  const inRecords = (field: string, kind: FinderKind) =>
    !!onPickFields &&
    (kind === 'empty' ||
      (kind === 'spelling' && recordFields.includes(field)) ||
      (kind === 'duplicates' && (field === ALL ? !!run.data?.combined : !commonOnly && !!run.data?.fields.find((f) => f.name === field)?.duplicates)));
  const tickable = [...(run.data?.fields ?? []).map((f) => f.name), ALL].filter((f) => inRecords(f, focus ?? 'empty'));
  const isOn = (field: string, kind: FinderKind) =>
    inRecords(field, kind) ? shownFields == null || shownFields.includes(field) : pick?.field === field && pick.kind === kind;
  const choose = (field: string, kind: FinderKind) => {
    if (!inRecords(field, kind)) return setPick({ field, kind });
    const now = shownFields ?? tickable;
    onPickFields!(now.includes(field) ? now.filter((f) => f !== field) : [...now, field]);
    document.getElementById('records-table')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <section className="mb-7 overflow-hidden rounded-xl border border-brand/25">
      <header className="flex flex-wrap items-center gap-3 border-b border-brand/15 bg-brand-soft/50 px-5 py-4">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand text-white">
          <ListChecks className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold">Check fields</h3>
          <p className="text-xs text-ink-muted">
            Pick fields — for each one you’ll see {focus === 'empty' ? 'its empty records' : focus === 'duplicates' ? 'its duplicates' : focus === 'spelling' ? 'its invalid values and why' : 'the empty records, the duplicates and the invalid values'}. Only the objects this check looked at ·
            read-only.
          </p>
        </div>
        {choices.length > 1 ? (
          <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Object">
            {choices.map((o) => (
              <button
                key={o}
                type="button"
                role="tab"
                aria-selected={object === o}
                onClick={() => setObject(o)}
                className={cx('rounded-full border px-3 py-1 text-xs font-medium transition', object === o ? 'border-brand bg-brand text-white' : 'border-line bg-surface hover:border-brand/40')}
              >
                {objectLabel(o)}
              </button>
            ))}
          </div>
        ) : (
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium">{objectLabel(object)}</span>
        )}
      </header>

      <div className="space-y-4 p-5">
        {options.isLoading ? (
          <LoadingState rows={3} label="Reading this object’s fields…" />
        ) : options.error ? (
          <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">{errorMessage(options.error)}</p>
        ) : (
          <>
            <div className="rounded-lg border border-line p-4">
              <div className={cx('flex flex-wrap items-center gap-3', listOpen && 'mb-3')}>
                <button
                  type="button"
                  onClick={() => setListOpen((o) => !o)}
                  aria-expanded={listOpen}
                  className="group flex min-w-0 flex-1 items-center gap-2 text-left text-sm"
                  title={listOpen ? 'Hide the field list' : 'Show the field list to change the fields'}
                >
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md border border-line bg-surface text-ink-muted transition group-hover:border-brand/40 group-hover:text-brand">
                    <ChevronDown className={cx('h-4 w-4 transition-transform', !listOpen && '-rotate-90')} />
                  </span>
                  Fields to check <span className="text-ink-muted">({chosen.length}/{MAX_FIELDS} chosen)</span>
                  {!listOpen && <span className="text-xs font-medium text-brand group-hover:underline">Change</span>}
                </button>
                {listOpen && (
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
                    <input className="input h-8 w-56 pl-8 text-xs" placeholder="Filter fields…" value={fieldQuery} onChange={(e) => setFieldQuery(e.target.value)} />
                  </div>
                )}
              </div>
              {chosen.length > 0 ? (
                <div className={cx('flex flex-wrap items-center gap-1 text-xs text-ink-muted', listOpen ? 'mb-2' : 'mt-2 pl-8')}>
                  <span className="mr-1">Checking:</span>
                  {chosen.map((f, i) => (
                    <span key={f} className="inline-flex items-center gap-1">
                      {i > 0 && andOr && mode !== 'CUSTOM' && (
                        <span className={cx('px-0.5 text-[10px] font-bold', mode === 'OR' ? 'text-warn' : 'text-brand')}>{mode}</span>
                      )}
                      <span className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2 py-0.5 font-medium text-ink">
                        {andOr && mode === 'CUSTOM' && (
                          <span className="grid h-4 min-w-4 place-items-center rounded-full bg-brand px-1 text-[10px] font-bold text-white">{i + 1}</span>
                        )}
                        {label(f)}
                      </span>
                    </span>
                  ))}
                  <button type="button" className="ml-2 text-brand hover:underline" onClick={() => (setChosen([]), setLogic(''), setListOpen(true))}>Clear</button>
                </div>
              ) : (
                !listOpen && <p className="mt-2 pl-8 text-xs text-ink-subtle">No fields picked yet. Open the list to choose some.</p>
              )}
              {listOpen && (
              <div className="scrollbar-thin grid max-h-64 gap-1.5 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
                {fieldList.map((f) => {
                  const on = chosen.includes(f.name);
                  return (
                    <label
                      key={f.name}
                      className={cx(
                        'flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm transition',
                        on ? 'border-brand bg-brand-soft/60' : 'border-line hover:border-brand/30',
                        !on && chosen.length >= MAX_FIELDS && 'cursor-not-allowed opacity-50',
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 accent-[rgb(var(--brand))]"
                        checked={on}
                        disabled={!on && chosen.length >= MAX_FIELDS}
                        onChange={(e) => setChosen(e.target.checked ? [...chosen, f.name] : chosen.filter((x) => x !== f.name))}
                      />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{f.label}</span>
                        <span className="block truncate text-[11px] text-ink-subtle">{f.name} · {f.type}</span>
                      </span>
                    </label>
                  );
                })}
                {fieldList.length === 0 && <p className="text-xs text-ink-subtle">No fields match “{fieldQuery}”.</p>}
              </div>
              )}
            </div>

            {shows('duplicates') && presets.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="mr-1 font-medium text-ink-muted">Duplicate checks:</span>
                {presets.map((p) => {
                  const on = !p.missing && p.names.length === chosen.length && p.names.every((n) => chosen.includes(n)) && mode === 'AND';
                  return (
                    <button
                      key={p.label}
                      type="button"
                      disabled={p.missing || run.isPending}
                      onClick={() => applyPreset(p.names)}
                      title={p.missing ? `${p.help} This org’s ${objectLabel(object)} don’t have all of these fields.` : `${p.help} Click to check.`}
                      className={cx(
                        'rounded-full border px-3 py-1 font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
                        on ? 'border-brand bg-brand text-white' : 'border-line bg-surface hover:border-brand/40 hover:text-brand',
                      )}
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" icon={<ListChecks className="h-4 w-4" />} disabled={!chosen.length || run.isPending || (mode === 'CUSTOM' && !!logicError)} onClick={start}>
                {run.isPending ? 'Checking…' : `Check ${chosen.length || ''} field${chosen.length === 1 ? '' : 's'}`.replace('  ', ' ')}
              </Button>
              {run.isPending && <span className="text-xs text-ink-muted">Reading up to 20,000 {what} and checking each field…</span>}
            </div>
            {run.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(run.error)}</p>}
          </>
        )}

        {result && (
          <div className="space-y-4">
            <div className="space-y-3">
            <div className="flex flex-wrap items-start gap-2">
            <p className="min-w-0 flex-1 text-sm">
              <span className="font-semibold tabular-nums">{fmtNumber(result.scanned)}</span> {what} checked
              {result.truncated && <span className="text-ink-muted"> (the first 20,000)</span>}. {onPickFields ? 'Tick a field to show its records in the table below.' : 'Click a number to see its records.'}
              {tickable.length > 1 && (
                <span className="ml-2 whitespace-nowrap text-xs">
                  <button type="button" className="font-semibold text-brand hover:underline disabled:text-ink-subtle disabled:no-underline" disabled={shownFields == null || tickable.every((f) => shownFields.includes(f))} onClick={() => onPickFields!(null)}>
                    Select all
                  </button>
                  <span className="mx-1.5 text-ink-subtle">·</span>
                  <button type="button" className="font-semibold text-brand hover:underline disabled:text-ink-subtle disabled:no-underline" disabled={shownFields?.length === 0} onClick={() => onPickFields!([])}>
                    Deselect all
                  </button>
                </span>
              )}
            </p>
            </div>
              {andOr && result && (
                <div className="space-y-2 rounded-lg border border-line px-4 py-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-ink-muted">Duplicates when the fields match:</span>
                    <span className="inline-flex overflow-hidden rounded-lg border border-line" role="radiogroup" aria-label="How the fields combine">
                      {MODES.map((m) => (
                        <button
                          key={m.value}
                          type="button"
                          role="radio"
                          aria-checked={mode === m.value}
                          title={m.help}
                          onClick={() => pickMode(m.value, true)}
                          className={cx(
                            'border-l border-line px-3 py-1 font-semibold transition first:border-l-0',
                            mode === m.value ? 'bg-brand text-white' : 'bg-surface text-ink-muted hover:text-brand',
                          )}
                        >
                          {m.label}
                        </button>
                      ))}
                    </span>
                    <span className="text-ink-subtle">{MODES.find((m) => m.value === mode)!.help}</span>
                  </div>
                  {mode === 'AND' && chosen.length > MAX_GROUP_FIELDS && (
                    <p className="text-warn">Only the first {MAX_GROUP_FIELDS} fields are compared together.</p>
                  )}
                  {mode === 'CUSTOM' && (
                    <div className="space-y-1">
                      <label className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-ink-muted">Condition</span>
                        <input
                          className={cx('input h-8 w-72 font-mono text-xs', logicError && 'border-bad')}
                          value={logic}
                          onChange={(e) => setLogic(e.target.value)}
                          placeholder="e.g. 1 AND (2 OR 3)"
                          aria-label="Custom condition"
                          onKeyDown={(e) => e.key === 'Enter' && !logicError && runWith(chosen, true, 'CUSTOM')}
                        />
                        <Button size="sm" variant="primary" disabled={!!logicError || run.isPending} onClick={() => runWith(chosen, true, 'CUSTOM')}>
                          Apply
                        </Button>
                      </label>
                      {logicError ? (
                        <p className="text-bad">{logicError}</p>
                      ) : (
                        parsed && 'groups' in parsed && (
                          <p className="text-ink-subtle">
                            Duplicates when: {ruleText(parsed.groups.map((g) => g.map((k) => label(chosen[k - 1]))))}
                          </p>
                        )
                      )}
                    </div>
                  )}
                </div>
              )}
            <div className="scrollbar-thin overflow-auto rounded-xl border border-line">
              <table className={cx('w-full text-left text-sm', !focus && 'min-w-[640px]')}>
                <thead className="bg-muted/50 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                  <tr>
                    <th className="px-3 py-2">Field</th>
                    <th className="px-3 py-2">Filled in</th>
                    {shows('empty') && <th className="px-3 py-2">Empty</th>}
                    {shows('duplicates') && <th className="px-3 py-2">Duplicates</th>}
                    {shows('spelling') && <th className="px-3 py-2">Invalid data</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {result.fields.filter(() => !(commonOnly && focus === 'duplicates')).map((f) => (
                    <tr key={f.name}>
                      <td className="px-3 py-2">
                        <span className="block font-medium">{f.label}</span>
                        <span className="block text-[11px] text-ink-subtle">{f.name}</span>
                      </td>
                      <td className="px-3 py-2 tabular-nums text-ink-muted">
                        {fmtNumber(f.filled)}
                      </td>
                      {shows('empty') && (
                        <Cell on={isOn(f.name, 'empty')} onClick={() => choose(f.name, 'empty')} tick={inRecords(f.name, 'empty')} value={f.empty} hint="records" tone="text-bad" />
                      )}
                      {shows('duplicates') && (
                        <Cell
                          on={isOn(f.name, 'duplicates')}
                          onClick={() => choose(f.name, 'duplicates')}
                          tick={inRecords(f.name, 'duplicates')}
                          value={f.duplicates ? f.duplicates.extraCopies + f.duplicates.totalGroups : undefined}
                          hint={f.duplicates ? `duplicate records · ${fmtNumber(f.duplicates.totalGroups)} groups` : undefined}
                          tone="text-warn"
                          none="Picklist choices, dates and numbers are shared by design, so they’re only duplicates together with other fields."
                        />
                      )}
                      {shows('spelling') && (
                        <Cell
                          on={isOn(f.name, 'spelling')}
                          onClick={() => choose(f.name, 'spelling')}
                          tick={inRecords(f.name, 'spelling')}
                          value={f.standardization?.oddRecords}
                          hint={f.standardization ? `records · ${fmtNumber(f.standardization.valuesWithVariants)} values` : undefined}
                          tone="text-warn"
                          none="Only text fields are checked for spelling."
                        />
                      )}
                    </tr>
                  ))}
                  {result.combined && shows('duplicates') && (
                    <tr className="bg-brand-soft/30">
                      <td className="px-3 py-2">
                        <span className="block font-medium">{ranMode === 'CUSTOM' ? 'Custom condition' : result.combined.rules.length > 1 ? 'Match rule (AND / OR)' : 'All fields together (AND)'}</span>
                        <span className="block text-[11px] text-ink-subtle">{ruleText(result.combined.rules)}</span>
                      </td>
                      <td className="px-3 py-2 text-ink-subtle">—</td>
                      {shows('empty') && <td className="px-3 py-2 text-ink-subtle">—</td>}
                      <Cell
                        on={isOn(ALL, 'duplicates')}
                        onClick={() => choose(ALL, 'duplicates')}
                        tick={inRecords(ALL, 'duplicates')}
                        value={result.combined.extraCopies + result.combined.totalGroups}
                        hint={`duplicate records · ${fmtNumber(result.combined.totalGroups)} groups`}
                        tone="text-warn"
                      />
                      {shows('spelling') && <td className="px-3 py-2 text-ink-subtle">—</td>}
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            </div>

            {pick && !inRecords(pick.field, pick.kind) && (
              <div className="rounded-xl border border-line p-4">
                <h4 className="mb-3 text-sm font-semibold">
                  {pick.field === ALL
                    ? `Duplicates on ${ruleText(result.combined?.rules ?? [])}`
                    : pick.kind === 'empty'
                      ? `${objectLabel(object)} with no ${picked?.label}`
                      : pick.kind === 'duplicates'
                        ? `Duplicates on ${picked?.label}`
                        : `${picked?.label}: invalid data and why`}
                </h4>
                {pick.field === ALL && result.combined ? (
                  <DuplicateResults result={result.combined} fileName={`duplicate-${object.toLowerCase()}s.csv`} />
                ) : picked && pick.kind === 'empty' ? (
                  <EmptyRecords object={object} fields={[picked.name]} />
                ) : picked && pick.kind === 'duplicates' && picked.duplicates ? (
                  <DuplicateResults result={picked.duplicates} fileName={`duplicate-${object.toLowerCase()}s-${picked.name.toLowerCase()}.csv`} />
                ) : picked && pick.kind === 'spelling' && picked.standardization ? (
                  <SpellingResults field={picked} object={result.object} />
                ) : (
                  <p className="text-sm text-ink-muted">This isn’t checked for {picked?.label}.</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
