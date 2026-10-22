import { ChevronRight, CircleOff, Copy, Download, ExternalLink, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { errorMessage } from '@/api/client';
import { useDuplicateOptions, useFindDuplicates } from '@/api/queries';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { DuplicateResult } from '@/types';
import { Button } from '../ui/Button';
import { LoadingState } from '../ui/States';
import { AnimatedNumber } from '../ui/Visuals';
import { EmptyFieldsFinder } from './EmptyFieldsFinder';

const COMMON_OBJECTS = ['Account', 'Contact', 'Lead', 'Opportunity'];
const MAX_FIELDS = 6;

function show(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'object') return String((v as Record<string, unknown>).Name ?? '—');
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fmtDate(v); // Created Date etc.
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

/** The result as a sequence: checked → duplicates found → groups → kept → extra copies. */
function DuplicateFlow({ result }: { result: DuplicateResult }) {
  const what = objectLabel(result.object).toLowerCase();
  const inGroups = result.extraCopies + result.totalGroups;
  const pct = (n: number) => (result.scanned ? `${Math.round((100 * n) / result.scanned)}% of all ${what}` : '');
  // How big the groups are (all groups are returned, so this is exact).
  const sizes = result.groups.reduce<Record<string, number>>((m, g) => {
    const k = g.size >= 5 ? '5+' : String(g.size);
    m[k] = (m[k] ?? 0) + 1;
    return m;
  }, {});
  const sizeText = ['2', '3', '4', '5+']
    .filter((k) => sizes[k])
    .map((k) => `${fmtNumber(sizes[k])} of ${k}`)
    .join(' · ');

  const steps: { n: number; label: string; value: number; plus?: boolean; hint: string; tone: string }[] = [
    { n: 1, label: `${objectLabel(result.object)} checked`, value: result.scanned, plus: result.truncated, hint: 'Every record read from Salesforce', tone: 'text-ink' },
    { n: 2, label: 'Duplicate records found', value: inGroups, hint: `${pct(inGroups)} match at least one other`, tone: 'text-warn' },
    { n: 3, label: 'Duplicate groups', value: result.totalGroups, hint: sizeText ? `Group sizes: ${sizeText}` : 'Sets that match each other', tone: 'text-ink' },
    { n: 4, label: 'Keep one per group', value: result.totalGroups, hint: 'The record you keep in each group', tone: 'text-good' },
    { n: 5, label: 'Extra copies to merge', value: result.extraCopies, hint: `${fmtNumber(inGroups)} found − ${fmtNumber(result.totalGroups)} kept · ${pct(result.extraCopies)}`, tone: 'text-bad' },
  ];

  return (
    <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {steps.map((st, i) => (
        <li key={st.n} className="relative flex">
          <div className={cx('flex w-full flex-col rounded-xl border px-4 py-3', st.n === 5 ? 'border-bad/30 bg-bad-soft/40' : st.n === 2 ? 'border-warn/30 bg-warn-soft/40' : 'border-line bg-muted/40')}>
            <span className="flex items-center gap-2 text-xs font-medium text-ink-muted">
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface text-[11px] font-bold text-ink ring-1 ring-line">{st.n}</span>
              {st.label}
            </span>
            <span className={cx('mt-1.5 text-2xl font-semibold tabular-nums tracking-tight', st.tone)}>
              <AnimatedNumber value={st.value} />
              {st.plus ? '+' : ''}
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

/** Check an object's data: duplicates on the fields the person chooses, or records with empty fields. */
export function DuplicateFinder({ objects, initialObject }: { objects: string[]; initialObject?: string | null }) {
  const choices = useMemo(() => Array.from(new Set([...(initialObject ? [initialObject] : []), ...objects, ...COMMON_OBJECTS])), [objects, initialObject]);
  const [object, setObject] = useState(initialObject ?? choices[0]);
  const options = useDuplicateOptions(object);
  const [tab, setTab] = useState<'duplicates' | 'empty'>('duplicates');
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

  const fields = options.data?.fields ?? [];
  const fieldList = fields.filter((f) => !fieldQuery || `${f.label} ${f.name}`.toLowerCase().includes(fieldQuery.toLowerCase()));
  const label = (name: string) => fields.find((f) => f.name === name)?.label ?? name;
  const canRun = chosen.length > 0;

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
          <h3 className="font-semibold">Check your data</h3>
          <p className="text-xs text-ink-muted">Find duplicates on the fields you choose, or records where chosen fields are empty. Read-only — nothing is changed.</p>
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
        <div className="flex flex-wrap gap-2" role="tablist">
          {([
            ['duplicates', 'Duplicates', Copy],
            ['empty', 'Empty fields', CircleOff],
          ] as const).map(([t, text, Icon]) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cx('inline-flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition', tab === t ? 'border-brand bg-brand text-white' : 'border-line hover:border-brand/40')}
            >
              <Icon className="h-4 w-4" /> {text}
            </button>
          ))}
        </div>

        {tab === 'empty' && <EmptyFieldsFinder object={object} />}

        {tab === 'duplicates' && (
          <>
        {options.isLoading ? (
          <LoadingState rows={3} label="Reading this object’s fields…" />
        ) : options.error ? (
          <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">{errorMessage(options.error)}</p>
        ) : (
          <>
            {(
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
              <Button variant="primary" icon={<Search className="h-4 w-4" />} disabled={!canRun || run.isPending} onClick={() => run.mutate({ object, standard: false, fields: chosen })}>
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
            <DuplicateFlow result={result} />
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
          </>
        )}
      </div>
    </section>
  );
}
