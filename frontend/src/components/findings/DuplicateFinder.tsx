import { Copy, Download, ExternalLink, Search, SlidersHorizontal, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { errorMessage } from '@/api/client';
import { useDuplicateOptions, useFindDuplicates } from '@/api/queries';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { cx, fmtNumber } from '@/lib/format';
import type { DuplicateResult } from '@/types';
import { Button } from '../ui/Button';
import { LoadingState } from '../ui/States';

const STANDARD_OBJECTS = ['Account', 'Contact', 'Lead'];
const MAX_FIELDS = 6;

function show(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'object') return String((v as Record<string, unknown>).Name ?? '—');
  return String(v);
}

function toCsv(r: DuplicateResult): string {
  const cell = (s: string) => `"${s.replace(/"/g, '""')}"`;
  const head = ['Group', 'Records in group', 'Matched on', ...r.columns.map((c) => c.label), 'Salesforce link'];
  const lines = r.groups.flatMap((g, i) =>
    g.records.map((rec) => [String(i + 1), String(g.size), g.matchedOn, ...r.columns.map((c) => show(rec.values[c.name])), rec.id ? `${r.recordUrlPrefix}${rec.id}` : ''].map(cell).join(',')),
  );
  return '﻿' + [head.map(cell).join(','), ...lines].join('\r\n');
}

/** Find duplicates by Salesforce's standard matching rule, or on fields the person chooses. Results are grouped. */
export function DuplicateFinder({ objects, initialObject }: { objects: string[]; initialObject?: string | null }) {
  const choices = useMemo(() => Array.from(new Set([...(initialObject ? [initialObject] : []), ...objects, ...STANDARD_OBJECTS])), [objects, initialObject]);
  const [object, setObject] = useState(initialObject ?? choices[0]);
  const options = useDuplicateOptions(object);
  const hasStandard = !!options.data?.standardRule;
  const [mode, setMode] = useState<'standard' | 'fields'>('standard');
  const [chosen, setChosen] = useState<string[]>([]);
  const [fieldQuery, setFieldQuery] = useState('');
  const [resultQuery, setResultQuery] = useState('');
  const [minSize, setMinSize] = useState(2);
  const run = useFindDuplicates();

  // A different page (problem or measure) opened in the same place: start from its object.
  useEffect(() => {
    if (initialObject) setObject(initialObject);
  }, [initialObject]);
  useEffect(() => {
    setChosen([]);
    setFieldQuery('');
    run.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [object]);
  useEffect(() => {
    if (options.data) setMode(options.data.standardRule ? 'standard' : 'fields');
  }, [options.data]);

  const fields = options.data?.fields ?? [];
  const fieldList = fields.filter((f) => !fieldQuery || `${f.label} ${f.name}`.toLowerCase().includes(fieldQuery.toLowerCase()));
  const label = (name: string) => fields.find((f) => f.name === name)?.label ?? name;
  const canRun = mode === 'standard' ? hasStandard : chosen.length > 0;

  const result = run.data;
  const term = resultQuery.trim().toLowerCase();
  const groups = (result?.groups ?? [])
    .map((g, i) => ({ ...g, n: i + 1 }))
    .filter((g) => g.size >= minSize && (!term || g.records.some((rec) => Object.values(rec.values).some((v) => show(v).toLowerCase().includes(term)))));

  const download = () => {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([toCsv(result)], { type: 'text/csv;charset=utf-8' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: `duplicate-${object.toLowerCase()}s.csv` });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="mb-7 overflow-hidden rounded-xl border border-brand/25">
      <header className="flex flex-wrap items-center gap-3 border-b border-brand/15 bg-brand-soft/50 px-5 py-4">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand text-white">
          <Copy className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold">Find duplicates</h3>
          <p className="text-xs text-ink-muted">Use Salesforce’s standard matching rule, or choose exactly which fields must match. Read-only — nothing is changed.</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-ink-muted">Object</span>
          <select className="input h-9 w-auto py-0" value={object} onChange={(e) => setObject(e.target.value)}>
            {choices.map((o) => (
              <option key={o} value={o}>{objectLabel(o)}</option>
            ))}
          </select>
        </label>
      </header>

      <div className="space-y-4 p-5">
        {options.isLoading ? (
          <LoadingState rows={3} label="Reading this object’s fields…" />
        ) : options.error ? (
          <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">{errorMessage(options.error)}</p>
        ) : (
          <>
            {/* how to match */}
            <div className="flex flex-wrap gap-2">
              {([
                ['standard', 'Salesforce standard rule', Sparkles, !hasStandard],
                ['fields', 'Choose fields', SlidersHorizontal, false],
              ] as const).map(([m, text, Icon, disabled]) => (
                <button
                  key={m}
                  type="button"
                  disabled={disabled}
                  onClick={() => setMode(m)}
                  title={disabled ? 'Salesforce has a standard rule only for Accounts, Contacts and Leads' : undefined}
                  className={cx(
                    'inline-flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40',
                    mode === m ? 'border-brand bg-brand text-white' : 'border-line hover:border-brand/40',
                  )}
                >
                  <Icon className="h-4 w-4" /> {text}
                </button>
              ))}
            </div>

            {mode === 'standard' && options.data?.standardRule && (
              <div className="rounded-lg border border-line bg-muted/40 p-4 text-sm">
                <p className="font-medium">{options.data.standardRule}</p>
                <p className="mt-1 text-xs text-ink-muted">Two records are duplicates when every field in <strong>any one</strong> of these groups matches:</p>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {options.data.standardGroups.map((g, i) => (
                    <li key={i} className="rounded-full bg-surface px-2.5 py-1 text-xs ring-1 ring-line">
                      {g.join(' + ')}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] text-ink-subtle">Blank fields never match. Names allow typos, nicknames and first/last swapped; phones, streets and ZIPs are compared in parts — as Salesforce does.</p>
              </div>
            )}

            {mode === 'fields' && (
              <div className="rounded-lg border border-line p-4">
                <div className="mb-3 flex flex-wrap items-center gap-3">
                  <p className="min-w-0 flex-1 text-sm">
                    Records are duplicates when <strong>all</strong> the fields you pick match.{' '}
                    <span className="text-ink-muted">({chosen.length}/{MAX_FIELDS} chosen)</span>
                  </p>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
                    <input className="input h-8 w-56 pl-8 text-xs" placeholder="Filter fields…" value={fieldQuery} onChange={(e) => setFieldQuery(e.target.value)} />
                  </div>
                </div>
                {chosen.length > 0 && (
                  <p className="mb-2 text-xs text-ink-muted">
                    Matching on: <span className="font-medium text-ink">{chosen.map(label).join(' + ')}</span>
                    <button type="button" className="ml-2 text-brand hover:underline" onClick={() => setChosen([])}>Clear</button>
                  </p>
                )}
                <div className="scrollbar-thin grid max-h-64 gap-1.5 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
                  {fieldList.map((f) => {
                    const on = chosen.includes(f.name);
                    return (
                      <label
                        key={f.name}
                        title={f.method}
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
                          <span className="block truncate text-[11px] text-ink-subtle">{f.method}</span>
                        </span>
                      </label>
                    );
                  })}
                  {fieldList.length === 0 && <p className="text-xs text-ink-subtle">No fields match “{fieldQuery}”.</p>}
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" icon={<Search className="h-4 w-4" />} disabled={!canRun || run.isPending} onClick={() => run.mutate({ object, standard: mode === 'standard', fields: chosen })}>
                {run.isPending ? 'Looking for duplicates…' : `Find duplicate ${objectLabel(object).toLowerCase()}`}
              </Button>
              {run.isPending && <span className="text-xs text-ink-muted">Reading up to 20,000 {objectLabel(object).toLowerCase()} from Salesforce…</span>}
            </div>
            {run.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(run.error)}</p>}
          </>
        )}

        {/* results */}
        {result && (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                ['Duplicate groups', fmtNumber(result.totalGroups), `Sets of ${objectLabel(result.object).toLowerCase()} that match each other`],
                [
                  'Extra copies',
                  fmtNumber(result.extraCopies),
                  `Records to merge away if you keep one per group (${fmtNumber(result.extraCopies + result.totalGroups)} in groups − ${fmtNumber(result.totalGroups)} kept)`,
                ],
                [
                  `${objectLabel(result.object)} checked`,
                  `${fmtNumber(result.scanned)}${result.truncated ? '+' : ''}`,
                  result.scanned ? `${Math.round((100 * result.extraCopies) / result.scanned)}% of them are extra copies` : '',
                ],
              ].map(([k, v, hint]) => (
                <div key={k} className="rounded-lg border border-line bg-muted/40 px-4 py-3">
                  <p className="text-xs text-ink-subtle">{k}</p>
                  <p className="text-xl font-semibold tabular-nums">{v}</p>
                  {hint && <p className="mt-0.5 text-[11px] leading-snug text-ink-muted">{hint}</p>}
                </div>
              ))}
            </div>
            <p className="text-xs text-ink-muted">
              Matched on: {result.rules.map((g) => g.join(' + ')).join('  ·  or  ·  ')}.
              {result.truncated && ' Only the first 20,000 records were read.'}
              {result.groups.length < result.totalGroups && ` Showing the ${fmtNumber(result.groups.length)} largest groups.`}
            </p>

            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
                <input className="input h-9 pl-8 text-sm" placeholder="Filter results by any value (name, email, city…)" value={resultQuery} onChange={(e) => setResultQuery(e.target.value)} />
              </div>
              <label className="flex items-center gap-2 text-xs text-ink-muted">
                Group size
                <select className="input h-9 w-auto py-0 text-sm" value={minSize} onChange={(e) => setMinSize(Number(e.target.value))}>
                  {[2, 3, 4, 5, 10].map((n) => (
                    <option key={n} value={n}>{n === 2 ? 'Any' : `${n} or more`}</option>
                  ))}
                </select>
              </label>
              <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={download} disabled={!result.groups.length}>
                CSV
              </Button>
            </div>

            {groups.length === 0 ? (
              <p className="rounded-lg bg-muted/50 px-4 py-6 text-center text-sm text-ink-muted">
                {result.totalGroups ? 'No groups match this filter.' : 'No duplicates found with these rules.'}
              </p>
            ) : (
              <div className="scrollbar-thin max-h-[32rem] overflow-auto rounded-xl border border-line">
                <table className="w-full min-w-[720px] text-left text-xs">
                  <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
                    <tr>
                      <th className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">Group</th>
                      {result.columns.map((c) => (
                        <th key={c.name} className="whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">{c.label}</th>
                      ))}
                      <th className="w-8" />
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((g, gi) =>
                      g.records.map((rec, ri) => (
                        <tr key={`${g.n}-${rec.id ?? ri}`} className={cx('group hover:bg-muted/60', gi % 2 === 1 && 'bg-brand-soft/30', ri === 0 && gi > 0 && 'border-t-2 border-t-brand/20')}>
                          <td className="whitespace-nowrap px-3 py-2 align-top">
                            {ri === 0 && (
                              <span className="inline-flex flex-col">
                                <span className="w-fit rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-brand-ink ring-1 ring-brand/20">#{g.n} · {g.size}</span>
                                <span className="mt-1 text-[10px] text-ink-subtle">{g.matchedOn}</span>
                              </span>
                            )}
                          </td>
                          {result.columns.map((c, ci) => (
                            <td key={c.name} className="max-w-[16rem] truncate px-3 py-2" title={show(rec.values[c.name])}>
                              {ci === 0 && rec.id ? (
                                <a href={`${result.recordUrlPrefix}${rec.id}`} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-brand hover:underline">
                                  {show(rec.values[c.name])}
                                </a>
                              ) : (
                                <span className={show(rec.values[c.name]) === '—' ? 'text-ink-subtle' : ''}>{show(rec.values[c.name])}</span>
                              )}
                            </td>
                          ))}
                          <td className="px-2">
                            {rec.id && (
                              <a href={`${result.recordUrlPrefix}${rec.id}`} target="_blank" rel="noopener noreferrer" aria-label="Open in Salesforce" className="text-ink-subtle opacity-0 transition hover:text-brand group-hover:opacity-100">
                                <ExternalLink className="h-3.5 w-3.5" />
                              </a>
                            )}
                          </td>
                        </tr>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
