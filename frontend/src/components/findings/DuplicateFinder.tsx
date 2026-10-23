import { ChevronRight, Download, ExternalLink, Search } from 'lucide-react';
import { useState } from 'react';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { DuplicateResult } from '@/types';
import { Button } from '../ui/Button';
import { AnimatedNumber } from '../ui/Visuals';

export type FinderKind = 'duplicates' | 'empty' | 'spelling';

/** Which result a measure is about (duplicates, empty values or odd spellings) and the fields it looked at; null when
 *  it isn't about the values of fields. */
export function finderFor(name: string, criteria: [string, string][] = []): { kind: FinderKind; fieldsText: string } | null {
  const fieldsText = criteria.find(([k]) => k === 'Fields checked' || k === 'Compared on')?.[1] ?? '';
  if (/duplicate/i.test(name)) return { kind: 'duplicates', fieldsText };
  if (/standardi[sz]|inconsistent|spell/i.test(name)) return { kind: 'spelling', fieldsText };
  if (criteria.some(([k]) => k === 'Counts as missing' || k === 'Incomplete lead') || /missing|incomplete|completeness|empty|blank/i.test(name))
    return { kind: 'empty', fieldsText };
  return null;
}


export function show(v: unknown): string {
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
  // How big the groups are (exact unless only the largest groups were returned).
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
    { n: 3, label: 'Duplicate groups', value: result.totalGroups, hint: sizeText ? `${result.groups.length < result.totalGroups ? `Largest ${fmtNumber(result.groups.length)}` : 'Group sizes'}: ${sizeText}` : 'Sets that match each other', tone: 'text-ink' },
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

/** Duplicate groups: the numbered flow, a filter, group size, CSV and the grouped table. */
export function DuplicateResults({ result, fileName }: { result: DuplicateResult; fileName: string }) {
  const [query, setQuery] = useState('');
  const [minSize, setMinSize] = useState(2);
  const term = query.trim().toLowerCase();
  const groups = result.groups
    .map((g, i) => ({ ...g, n: i + 1 }))
    .filter((g) => g.size >= minSize && (!term || g.records.some((rec) => Object.values(rec.values).some((v) => show(v).toLowerCase().includes(term)))));

  const download = () => {
    const url = URL.createObjectURL(new Blob([toCsv(result)], { type: 'text/csv;charset=utf-8' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: fileName });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-3">
      <DuplicateFlow result={result} />
      <p className="text-xs text-ink-muted">
        Matched on: {result.rules.map((g) => g.join(' + ')).join('  ·  or  ·  ')}
        {result.methods.length > 0 && ` (${result.methods.map((m) => `${m.field}: ${m.method}`).join('; ')})`}.
        {result.truncated && ' Only the first 20,000 records were read.'}
        {result.groups.length < result.totalGroups && ` Showing the ${fmtNumber(result.groups.length)} largest groups.`}
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
          <input className="input h-9 pl-8 text-sm" placeholder="Filter results by any value (name, email, city…)" value={query} onChange={(e) => setQuery(e.target.value)} />
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
          {result.totalGroups ? 'No groups match this filter.' : 'No duplicates found.'}
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
  );
}
