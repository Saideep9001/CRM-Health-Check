import { ChevronDown, ListChecks, Search } from 'lucide-react';
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

const MAX_FIELDS = 10;
const ALL = '__all__'; // the "all chosen fields together" row

type Pick = { field: string; kind: FinderKind };

/** Values of one field written different ways, and the records using a less common spelling. */
function SpellingResults({ field, prefix }: { field: FieldCheckField; prefix: string }) {
  const std = field.standardization!;
  const [query, setQuery] = useState('');
  const term = query.trim().toLowerCase();
  const rows = std.records.filter((r) => !term || Object.values(r.values).some((v) => show(v).toLowerCase().includes(term)));
  if (!std.oddRecords) return <p className="rounded-lg bg-good-soft/50 px-4 py-6 text-center text-sm text-good">Every value of {field.label} is written the same way.</p>;
  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-muted">
        Values are the same once upper/lower case, punctuation and spaces are ignored (countries and US states also match their codes: “USA” = “United States”,
        “California” = “CA”). The most common spelling is treated as right; every record using another spelling counts.
      </p>
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
      {std.variants.length < std.valuesWithVariants && <p className="text-[11px] text-ink-subtle">Showing {std.variants.length} of {fmtNumber(std.valuesWithVariants)} values.</p>}

      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
        <input className="input h-9 pl-8 text-sm" placeholder="Filter records by any value…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div className="scrollbar-thin max-h-[28rem] overflow-auto rounded-xl border border-line">
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
              <tr key={r.id ?? ri} className="hover:bg-muted/60">
                {std.columns.map((c, ci) => (
                  <td key={c.name} className="max-w-[16rem] truncate px-3 py-2" title={show(r.values[c.name])}>
                    {ci === 0 && r.id ? (
                      <a href={`${prefix}${r.id}`} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-brand hover:underline">{show(r.values[c.name])}</a>
                    ) : (
                      <span className={c.name === field.name ? 'font-medium text-warn' : show(r.values[c.name]) === '—' ? 'text-ink-subtle' : ''}>{show(r.values[c.name])}</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {std.records.length < std.oddRecords && <p className="text-[11px] text-ink-subtle">Showing the first {fmtNumber(std.records.length)} of {fmtNumber(std.oddRecords)} records.</p>}
    </div>
  );
}

function Cell({ on, onClick, value, hint, tone, none }: { on: boolean; onClick?: () => void; value?: number; hint?: string; tone: string; none?: string }) {
  if (value === undefined) return <td className="px-3 py-2 text-ink-subtle" title={none}>—</td>;
  return (
    <td className="px-1.5 py-1.5">
      <button
        type="button"
        onClick={onClick}
        className={cx('w-full rounded-lg border px-2.5 py-1.5 text-left transition', on ? 'border-brand bg-brand-soft/60' : 'border-transparent hover:border-brand/30 hover:bg-muted/60')}
      >
        <span className={cx('block text-sm font-semibold tabular-nums', value ? tone : 'text-good')}>{fmtNumber(value)}</span>
        {hint && <span className="block text-[11px] text-ink-muted">{hint}</span>}
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
}: {
  objects: string[];
  initialObject?: string | null;
  focus?: FinderKind | null;
  fieldsText?: string;
  /** Tells the page about the latest run (null when it's reset), so its chart can follow the chosen fields. */
  onResult?: (result: FieldCheckResult | null) => void;
}) {
  // On a duplicates / missing / spelling page, only that page's column is shown.
  const shows = (k: FinderKind) => !focus || focus === k;
  const choices = useMemo(() => Array.from(new Set([...(initialObject ? [initialObject] : []), ...objects])), [objects, initialObject]);
  const [object, setObject] = useState(initialObject ?? choices[0]);
  const options = useEmptyOptions(object);
  const [chosen, setChosen] = useState<string[]>([]);
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
    setListOpen(named.length === 0); // fields already picked: keep the list folded
    setFieldQuery('');
    setPick(null);
    run.reset();
    onResult?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [object, fieldsText, options.data]);

  const fieldList = fields.filter((f) => !fieldQuery || `${f.label} ${f.name}`.toLowerCase().includes(fieldQuery.toLowerCase()));
  const label = (name: string) => fields.find((f) => f.name === name)?.label ?? name;
  const what = objectLabel(object).toLowerCase();

  const start = () => {
    setListOpen(false);
    run.mutate(
      { object, fields: chosen },
      {
        onSuccess: (r: FieldCheckResult) => {
          onResult?.(r);
          const kind = focus ?? 'empty';
          setPick({ field: kind === 'duplicates' && r.combined ? ALL : r.fields[0].name, kind });
        },
      },
    );
  };

  const result = run.data;
  const picked = result && pick ? (pick.field === ALL ? null : result.fields.find((f) => f.name === pick.field)) : null;
  const isOn = (field: string, kind: FinderKind) => pick?.field === field && pick.kind === kind;

  return (
    <section className="mb-7 overflow-hidden rounded-xl border border-brand/25">
      <header className="flex flex-wrap items-center gap-3 border-b border-brand/15 bg-brand-soft/50 px-5 py-4">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand text-white">
          <ListChecks className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold">Check fields</h3>
          <p className="text-xs text-ink-muted">
            Pick fields — for each one you’ll see {focus === 'empty' ? 'its empty records' : focus === 'duplicates' ? 'its duplicates' : focus === 'spelling' ? 'the values written different ways' : 'the empty records, the duplicates and the values written different ways'}. Only the objects this check looked at ·
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
                <p className={cx('text-xs text-ink-muted', listOpen ? 'mb-2' : 'mt-2 pl-8')}>
                  Checking: <span className="font-medium text-ink">{chosen.map(label).join(', ')}</span>
                  <button type="button" className="ml-2 text-brand hover:underline" onClick={() => (setChosen([]), setListOpen(true))}>Clear</button>
                </p>
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

            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" icon={<ListChecks className="h-4 w-4" />} disabled={!chosen.length || run.isPending} onClick={start}>
                {run.isPending ? 'Checking…' : `Check ${chosen.length || ''} field${chosen.length === 1 ? '' : 's'}`.replace('  ', ' ')}
              </Button>
              {run.isPending && <span className="text-xs text-ink-muted">Reading up to 20,000 {what} and checking each field…</span>}
            </div>
            {run.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(run.error)}</p>}
          </>
        )}

        {result && (
          <div className="space-y-4">
            <p className="text-sm">
              <span className="font-semibold tabular-nums">{fmtNumber(result.scanned)}</span> {what} checked
              {result.truncated && <span className="text-ink-muted"> (the first 20,000)</span>}. Click a number to see its records.
            </p>
            <div className="overflow-x-auto rounded-xl border border-line">
              <table className={cx('w-full text-left text-sm', !focus && 'min-w-[640px]')}>
                <thead className="bg-muted/50 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                  <tr>
                    <th className="px-3 py-2">Field</th>
                    <th className="px-3 py-2">Filled in</th>
                    {shows('empty') && <th className="px-3 py-2">Empty</th>}
                    {shows('duplicates') && <th className="px-3 py-2">Duplicates</th>}
                    {shows('spelling') && <th className="px-3 py-2">Written differently</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {result.fields.map((f) => (
                    <tr key={f.name}>
                      <td className="px-3 py-2">
                        <span className="block font-medium">{f.label}</span>
                        <span className="block text-[11px] text-ink-subtle">{f.name}</span>
                      </td>
                      <td className="px-3 py-2 tabular-nums text-ink-muted">
                        {fmtNumber(f.filled)} <span className="text-[11px]">({result.scanned ? Math.round((100 * f.filled) / result.scanned) : 0}%)</span>
                      </td>
                      {shows('empty') && (
                        <Cell on={isOn(f.name, 'empty')} onClick={() => setPick({ field: f.name, kind: 'empty' })} value={f.empty} hint="records" tone="text-bad" />
                      )}
                      {shows('duplicates') && (
                        <Cell
                          on={isOn(f.name, 'duplicates')}
                          onClick={() => setPick({ field: f.name, kind: 'duplicates' })}
                          value={f.duplicates?.extraCopies}
                          hint={f.duplicates ? `extra copies · ${fmtNumber(f.duplicates.totalGroups)} groups` : undefined}
                          tone="text-warn"
                          none="Picklist choices, dates, numbers and places (city, state, country, ZIP) are shared by design, so they’re only duplicates together with other fields."
                        />
                      )}
                      {shows('spelling') && (
                        <Cell
                          on={isOn(f.name, 'spelling')}
                          onClick={() => setPick({ field: f.name, kind: 'spelling' })}
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
                        <span className="block font-medium">All fields together</span>
                        <span className="block text-[11px] text-ink-subtle">{result.combined.rules[0]?.join(' + ')}</span>
                      </td>
                      <td className="px-3 py-2 text-ink-subtle">—</td>
                      {shows('empty') && <td className="px-3 py-2 text-ink-subtle">—</td>}
                      <Cell
                        on={isOn(ALL, 'duplicates')}
                        onClick={() => setPick({ field: ALL, kind: 'duplicates' })}
                        value={result.combined.extraCopies}
                        hint={`extra copies · ${fmtNumber(result.combined.totalGroups)} groups`}
                        tone="text-warn"
                      />
                      {shows('spelling') && <td className="px-3 py-2 text-ink-subtle">—</td>}
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {pick && (
              <div className="rounded-xl border border-line p-4">
                <h4 className="mb-3 text-sm font-semibold">
                  {pick.field === ALL
                    ? `Duplicates on ${result.combined?.rules[0]?.join(' + ')}`
                    : pick.kind === 'empty'
                      ? `${objectLabel(object)} with no ${picked?.label}`
                      : pick.kind === 'duplicates'
                        ? `Duplicates on ${picked?.label}`
                        : `${picked?.label} written different ways`}
                </h4>
                {pick.field === ALL && result.combined ? (
                  <DuplicateResults result={result.combined} fileName={`duplicate-${object.toLowerCase()}s.csv`} />
                ) : picked && pick.kind === 'empty' ? (
                  <EmptyRecords object={object} fields={[picked.name]} />
                ) : picked && pick.kind === 'duplicates' && picked.duplicates ? (
                  <DuplicateResults result={picked.duplicates} fileName={`duplicate-${object.toLowerCase()}s-${picked.name.toLowerCase()}.csv`} />
                ) : picked && pick.kind === 'spelling' && picked.standardization ? (
                  <SpellingResults field={picked} prefix={result.recordUrlPrefix} />
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
