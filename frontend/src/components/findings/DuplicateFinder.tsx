import { AlertTriangle, Check, ChevronRight, Download, ExternalLink, Filter, Maximize2, Minimize2, Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { DuplicateResult } from '@/types';
import { Button } from '../ui/Button';
import { InfoTip } from '../ui/HelpTip';
import { AnimatedNumber } from '../ui/Visuals';

export type FinderKind = 'duplicates' | 'empty' | 'spelling';

/** Which result a measure is about (duplicates, empty values or odd spellings) and the fields it looked at; null when
 *  it isn't about the values of fields. */
export function finderFor(name: string, criteria: [string, string][] = []): { kind: FinderKind; fieldsText: string } | null {
  // A card can name Check fields' starting fields itself; otherwise they're the fields it compared or checked.
  const fieldsText =
    criteria.find(([k]) => k === 'Check fields starts with')?.[1] ?? criteria.find(([k]) => k === 'Fields checked' || k === 'Compared on')?.[1] ?? '';
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
  const kept = result.kept ?? result.totalGroups;
  const inGroups = result.extraCopies + kept;
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

  const several = result.kept != null && result.rules.length > 1; // more than one field: a record can match on several
  const steps: { n: number; label: string; value: number; plus?: boolean; tip: string; hint?: string; tone: string }[] = [
    { n: 1, label: `${objectLabel(result.object)} checked`, value: result.scanned, plus: result.truncated, tone: 'text-ink',
      tip: `Every ${what.replace(/s$/, '')} record read live from Salesforce${result.truncated ? ' (the first 20,000)' : ''}.` },
    { n: 2, label: 'Duplicate records found', value: inGroups, tone: 'text-warn',
      tip: `Records that match at least one other record: ${pct(inGroups)}.${several ? ' A record that matches on more than one field is counted once.' : ''}` },
    { n: 3, label: 'Duplicate groups', value: result.totalGroups, tone: 'text-ink',
      tip: 'A group is a set of records that match each other on the fields shown. Each group is one real customer (or deal) entered more than once.',
      hint: sizeText ? `${result.groups.length < result.totalGroups ? `Largest ${fmtNumber(result.groups.length)}` : 'Group sizes'}: ${sizeText}` : 'Sets that match each other' },
    { n: 4, label: 'Keep one per group', value: kept, tone: 'text-good',
      tip: several ? 'One record to keep for each set of linked records (groups that share a record count as one set).' : 'In every group you keep one record, usually the most complete or most recently used one.' },
    { n: 5, label: 'Extra copies to merge', value: result.extraCopies, tone: 'text-bad',
      tip: `${fmtNumber(inGroups)} found − ${fmtNumber(kept)} kept = the copies to merge into the kept records (${pct(result.extraCopies)}).` },
  ];

  return (
    <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {steps.map((st, i) => (
        <li key={st.n} className="relative flex">
          <div className={cx('flex w-full flex-col rounded-xl border px-4 py-3', st.n === 5 ? 'border-bad/30 bg-bad-soft/40' : st.n === 2 ? 'border-warn/30 bg-warn-soft/40' : 'border-line bg-muted/40')}>
            <span className="flex items-center gap-2 text-xs font-medium text-ink-muted">
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface text-[11px] font-bold text-ink ring-1 ring-line">{st.n}</span>
              {st.label}
              <InfoTip label={`About ${st.label}`}>{st.tip}</InfoTip>
            </span>
            <span className={cx('mt-1.5 text-2xl font-semibold tabular-nums tracking-tight', st.tone)}>
              <AnimatedNumber value={st.value} />
              {st.plus ? '+' : ''}
            </span>
            {st.hint && <span className="mt-0.5 text-[11px] leading-snug text-ink-muted">{st.hint}</span>}
          </div>
          {i < steps.length - 1 && (
            <ChevronRight className="absolute -right-2.5 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 rounded-full bg-surface text-ink-subtle ring-1 ring-line lg:block" aria-hidden="true" />
          )}
        </li>
      ))}
    </ol>
  );
}

/** Values the group's records share are flagged (owner and dates of record keeping aren't: sharing them isn't a duplicate). */
const NOT_COMPARED = /^(OwnerId|Owner\.Name|CreatedDate|LastModifiedDate|LastActivityDate|SystemModstamp)$/;
// Picked from a list and shared by design: flagged only in a group matched on that field (e.g. "Stage on the same Account").
const SHARED_BY_DESIGN = /^(StageName|Type|Industry|LeadSource|Status|Rating|ForecastCategoryName|Salutation)$/;
function sameIn(records: { values: Record<string, unknown> }[], at: number, field: string, label: string, matchedOn: string): string | null {
  if (NOT_COMPARED.test(field) || (SHARED_BY_DESIGN.test(field) && !matchedOn.startsWith(label))) return null;
  const key = (v: unknown) => String(v ?? '').toLowerCase().replace(/^(https?:\/\/)?(www\d?\.)?/, '').replace(/[^a-z0-9]+/g, '');
  const mine = key(records[at].values[field]);
  if (!mine) return null;
  const others = records.filter((r, i) => i !== at && key(r.values[field]) === mine).length;
  return others ? `Same as ${others} other record${others > 1 ? 's' : ''} in this group` : null;
}

/** Excel-style filter for one column: tick the values to keep (with a search box for long lists). */
function ColumnFilter({ label, values, kept, onChange }: { label: string; values: [string, number][]; kept: Set<string> | null; onChange: (v: Set<string> | null) => void }) {
  const [open, setOpen] = useState(false);
  const [find, setFind] = useState('');
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const btn = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  const toggle = () => {
    const r = btn.current!.getBoundingClientRect();
    setPos({ top: r.bottom + 4, left: Math.max(8, Math.min(r.left, window.innerWidth - 272)) });
    setFind('');
    setOpen((o) => !o);
  };
  const t = find.trim().toLowerCase();
  const listed = values.filter(([v]) => !t || v.toLowerCase().includes(t));
  const isOn = (v: string) => !kept || kept.has(v);
  const flip = (v: string) => {
    const next = new Set(kept ?? values.map(([x]) => x));
    if (next.has(v)) next.delete(v);
    else next.add(v);
    onChange(next.size === values.length ? null : next);
  };
  return (
    <>
      <button
        ref={btn}
        type="button"
        onClick={toggle}
        aria-label={`Filter ${label}`}
        className={cx('ml-1 inline-grid h-5 w-5 place-items-center rounded align-middle hover:bg-muted', kept ? 'bg-brand-soft text-brand' : 'text-ink-subtle')}
      >
        <Filter className="h-3 w-3" />
      </button>
      {open &&
        createPortal(
          <div ref={box} style={{ position: 'fixed', top: pos.top, left: pos.left }} className="z-[70] w-64 rounded-xl border border-line bg-surface p-2 text-xs normal-case tracking-normal shadow-xl">
            <input autoFocus className="input mb-2 h-8 text-xs" placeholder={`Search ${label}…`} value={find} onChange={(e) => setFind(e.target.value)} />
            <div className="mb-1 flex justify-between px-1 text-[11px]">
              <button type="button" className="font-semibold text-brand hover:underline" onClick={() => onChange(null)}>Select all</button>
              <button type="button" className="font-semibold text-brand hover:underline" onClick={() => onChange(new Set())}>Clear</button>
            </div>
            <ul className="scrollbar-thin max-h-60 overflow-auto">
              {listed.map(([v, n]) => (
                <li key={v}>
                  <button type="button" onClick={() => flip(v)} className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-muted">
                    <span className={cx('grid h-3.5 w-3.5 shrink-0 place-items-center rounded border', isOn(v) ? 'border-brand bg-brand text-white' : 'border-line')}>
                      {isOn(v) && <Check className="h-2.5 w-2.5" />}
                    </span>
                    <span className={cx('min-w-0 flex-1 truncate', v === '—' && 'text-ink-subtle')}>{v === '—' ? '(Blank)' : v}</span>
                    <span className="tabular-nums text-ink-subtle">{fmtNumber(n)}</span>
                  </button>
                </li>
              ))}
              {listed.length === 0 && <li className="px-1.5 py-2 text-ink-subtle">No values match.</li>}
            </ul>
          </div>,
          document.body,
        )}
    </>
  );
}

/** Duplicate groups: the numbered flow, a filter, group size, CSV and the grouped table. `flag` = the fields whose
 *  shared values are flagged in red (the fields ticked in Check fields); null flags every compared field. */
export function DuplicateResults({ result, fileName, flag = null }: { result: DuplicateResult; fileName: string; flag?: string[] | null }) {
  const [query, setQuery] = useState('');
  const [minSize, setMinSize] = useState(2);
  const [colFilters, setColFilters] = useState<Record<string, Set<string>>>({});
  const [big, setBig] = useState(false);
  useEffect(() => {
    if (!big) return;
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setBig(false);
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [big]);
  const term = query.trim().toLowerCase();
  const keeps = (rec: { values: Record<string, unknown> }) => Object.entries(colFilters).every(([c, s]) => s.has(show(rec.values[c])));
  const groups = result.groups
    .map((g, i) => ({ ...g, n: i + 1, shown: g.records.map((rec, ri) => ({ rec, ri })).filter(({ rec }) => keeps(rec)) }))
    .filter((g) => g.size >= minSize && g.shown.length > 0 && (!term || g.records.some((rec) => Object.values(rec.values).some((v) => show(v).toLowerCase().includes(term)))));
  // Each column's values (with how many records have them) for its filter.
  const valuesOf = (c: string): [string, number][] => {
    const m = new Map<string, number>();
    for (const g of result.groups) for (const rec of g.records) m.set(show(rec.values[c]), (m.get(show(rec.values[c])) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  };
  const setFilter = (c: string, v: Set<string> | null) =>
    setColFilters((f) => {
      const next = { ...f };
      if (v) next[c] = v;
      else delete next[c];
      return next;
    });
  const filtering = Object.keys(colFilters).length > 0;

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
        <Button size="sm" variant="subtle" icon={<Maximize2 className="h-3.5 w-3.5" />} onClick={() => setBig(true)} disabled={!result.groups.length}>
          Expand
        </Button>
      </div>
      {filtering && (
        <p className="text-xs text-ink-muted">
          Column filters on: {Object.keys(colFilters).map((c) => result.columns.find((x) => x.name === c)?.label ?? c).join(', ')} ·{' '}
          <button type="button" className="font-semibold text-brand hover:underline" onClick={() => setColFilters({})}>Clear column filters</button>
        </p>
      )}

      {groups.length === 0 ? (
        <p className="rounded-lg bg-muted/50 px-4 py-6 text-center text-sm text-ink-muted">
          {result.totalGroups ? 'No groups match this filter.' : 'No duplicates found.'}
          {filtering && (
            <button type="button" className="ml-1 font-semibold text-brand hover:underline" onClick={() => setColFilters({})}>Clear column filters</button>
          )}
        </p>
      ) : (
        <>
        {big && <div className="fixed inset-0 z-[60] bg-ink/40 backdrop-blur-[2px]" onClick={() => setBig(false)} />}
        <div className={cx(big ? 'fixed inset-3 z-[61] flex flex-col rounded-2xl bg-surface p-4 shadow-2xl sm:inset-6' : 'relative')}>
        {big && (
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="text-sm font-semibold">
              Duplicates on {result.rules.map((r) => r.join(' + ')).join(' · ')}{' '}
              <span className="font-normal text-ink-muted">· {fmtNumber(groups.length)} groups shown</span>
            </p>
            <Button size="sm" icon={<Minimize2 className="h-3.5 w-3.5" />} onClick={() => setBig(false)}>
              Minimize
            </Button>
          </div>
        )}
        <div className={cx('scrollbar-thin overflow-auto rounded-xl border border-line', big ? 'min-h-0 flex-1' : 'max-h-[32rem]')}>
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
              <tr>
                <th className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">Group</th>
                {result.columns.map((c) => (
                  <th key={c.name} className="whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                    {c.label}
                    <ColumnFilter label={c.label} values={valuesOf(c.name)} kept={colFilters[c.name] ?? null} onChange={(v) => setFilter(c.name, v)} />
                  </th>
                ))}
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {groups.map((g, gi) =>
                g.shown.map(({ rec, ri }, si) => (
                  <tr key={`${g.n}-${rec.id ?? ri}`} className={cx('group hover:bg-muted/60', gi % 2 === 1 && 'bg-brand-soft/30', si === 0 && gi > 0 && 'border-t-2 border-t-brand/20')}>
                    <td className="whitespace-nowrap px-3 py-2 align-top">
                      {si === 0 && (
                        <span className="inline-flex flex-col">
                          <span className="w-fit rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-brand-ink ring-1 ring-brand/20">#{g.n} · {g.size}</span>
                          <span className="mt-1 text-[10px] text-ink-subtle">{g.matchedOn}</span>
                        </span>
                      )}
                    </td>
                    {result.columns.map((c, ci) => {
                      const same = flag && !flag.includes(c.name) ? null : sameIn(g.records, ri, c.name, c.label, g.matchedOn);
                      return (
                      <td
                        key={c.name}
                        className={cx('max-w-[16rem] truncate px-3 py-2', same && 'bg-bad-soft/60')}
                        title={same ? `${show(rec.values[c.name])}
Why it’s flagged: ${same}` : show(rec.values[c.name])}
                      >
                        {ci === 0 && rec.id ? (
                          <a href={`${result.recordUrlPrefix}${rec.id}`} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-brand hover:underline">
                            {show(rec.values[c.name])}
                          </a>
                        ) : (
                          <span className={show(rec.values[c.name]) === '—' ? 'text-ink-subtle' : ''}>{show(rec.values[c.name])}</span>
                        )}
                        {same && (
                          <span className="mt-0.5 flex min-w-[11rem] items-start gap-1 whitespace-normal text-[10.5px] font-medium leading-snug text-bad">
                            <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
                            {same}
                          </span>
                        )}
                      </td>
                      );
                    })}
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
        </div>
        </>
      )}
    </div>
  );
}
