import { AlertTriangle, Check, Download, ExternalLink, Filter, Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { DuplicateResult } from '@/types';
import { Button } from '../ui/Button';
import { InfoTip } from '../ui/HelpTip';
import { useExpand } from '@/components/ui/Expand';
import { FlowSteps } from './MeasureFlow';

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

/** The result as a sequence: checked → duplicates found → groups → extra copies (each step with an info tip). */
function DuplicateFlow({ result }: { result: DuplicateResult }) {
  const what = objectLabel(result.object).toLowerCase();
  const kept = result.kept ?? result.totalGroups;
  const found = result.extraCopies + kept;
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

  const several = result.kept != null && result.rules.length > 1;
  return (
    <FlowSteps
      steps={[
        { label: `${objectLabel(result.object)} checked`, value: result.scanned, suffix: result.truncated ? '+' : '', hint: 'Every record read from Salesforce' },
        { label: 'Duplicate records found', value: found, hint: `${pct(found)} match at least one other`, tone: 'warn',
          tip: several ? 'A record that matches on more than one field is counted once.' : undefined },
        { label: 'Duplicate groups', value: result.totalGroups,
          hint: sizeText ? `${result.groups.length < result.totalGroups ? `Largest ${fmtNumber(result.groups.length)}` : 'Group sizes'}: ${sizeText}` : 'Sets of records that match each other' },
        { label: 'Extra copies to merge', value: result.extraCopies, hint: `${fmtNumber(found)} found − ${fmtNumber(kept)} kept · ${pct(result.extraCopies)}`, tone: 'bad' },
      ]}
    />
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
          <div ref={box} style={{ position: 'fixed', top: pos.top, left: pos.left }} className="z-[90] w-64 rounded-xl border border-line bg-surface p-2 text-xs normal-case tracking-normal shadow-xl">
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

/** How records count as duplicates in the table: identical values, or the fuzzy rules the check used. */
type MatchMode = 'all' | 'exact' | 'relevant';
const MATCH_MODES: { value: MatchMode; label: string; option: string; help: string }[] = [
  { value: 'all', label: 'All', option: 'All matches', help: 'Every duplicate group: exact and relevant matches together.' },
  { value: 'exact', option: 'Exact match (deterministic)', label: 'Exact match', help: 'Deterministic: identical values on the matched fields (ignoring upper/lower case and extra spaces), e.g. “Aquarient Tech” = “aquarient tech”.' },
  { value: 'relevant', option: 'Relevant match (fuzzy)', label: 'Relevant match', help: 'Fuzzy / probabilistic: normalised values, so legal suffixes (Inc, Ltd, LLC), punctuation, abbreviations and small typos still match, e.g. “Aquarient Technologies” = “Aquarient Tech” = “Aquarient Ltd”.' },
];
/** A value compared exactly: same text apart from upper/lower case and spacing. */
const exactKey = (v: unknown) => (show(v) === '—' ? '' : String(typeof v === 'object' ? show(v) : v).trim().toLowerCase().replace(/\s+/g, ' '));

/** Duplicate groups: the numbered flow, a filter, exact or relevant match, CSV and the grouped table. `flag` = the fields whose
 *  shared values are flagged in red (the fields ticked in Check fields); null flags every compared field. */
export function DuplicateResults({ result, fileName, flag = null }: { result: DuplicateResult; fileName: string; flag?: string[] | null }) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<MatchMode>('all');
  const [colFilters, setColFilters] = useState<Record<string, Set<string>>>({});
  const ex = useExpand();
  const term = query.trim().toLowerCase();
  const keeps = (rec: { values: Record<string, unknown> }) => Object.entries(colFilters).every(([c, s]) => s.has(show(rec.values[c])));
  // The fields a group was matched on ("Account Name + Billing City"), as columns.
  const matchCols = (matchedOn: string) => {
    const labels = matchedOn.split(' + ').map((l) => l.trim());
    return result.columns.filter((c) => labels.includes(c.label)).map((c) => c.name);
  };
  // Exact match: how many other records in the group have identical values on every matched field.
  const exactTwins = (g: DuplicateResult['groups'][number]) => {
    const cols = matchCols(g.matchedOn);
    const key = (rec: { values: Record<string, unknown> }) => (cols.length ? cols.map((c) => exactKey(rec.values[c])) : ['']).join('\u0001');
    const keys = g.records.map(key);
    return keys.map((k, i) => (k.replace(/\u0001/g, '') ? keys.filter((x, j) => j !== i && x === k).length : 0));
  };
  const groups = result.groups
    .map((g, i) => {
      const twins = exactTwins(g);
      // Exact: only records with an identical twin. Relevant: groups whose records differ a little (not all identical).
      const fuzzy = twins.some((t) => t === 0);
      const inMode =
        mode === 'relevant' && !fuzzy ? [] : g.records.map((rec, ri) => ({ rec, ri })).filter(({ ri }) => mode !== 'exact' || twins[ri] > 0);
      return { ...g, n: i + 1, twins, cols: matchCols(g.matchedOn), count: inMode.length, shown: inMode.filter(({ rec }) => keeps(rec)) };
    })
    .filter((g) => g.count >= 2 && g.shown.length > 0 && (!term || g.records.some((rec) => Object.values(rec.values).some((v) => show(v).toLowerCase().includes(term)))));
  const shownRecords = groups.reduce((n, g) => n + g.count, 0);
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
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
          <input className="input h-9 pl-8 text-sm" placeholder="Filter results by any value (name, email, city…)" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          Match type
          <InfoTip label="Exact or relevant match">
            {MATCH_MODES.map((m) => (
              <span key={m.value} className="mb-1 block last:mb-0">
                <span className="font-semibold">{m.label}:</span> {m.help}
              </span>
            ))}
          </InfoTip>
          <select className="input h-9 w-auto py-0 text-sm" value={mode} onChange={(e) => setMode(e.target.value as MatchMode)} aria-label="Match type">
            {MATCH_MODES.map((m) => (
              <option key={m.value} value={m.value}>{m.option}</option>
            ))}
          </select>
        </label>
        <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={download} disabled={!result.groups.length}>
          CSV
        </Button>
        {ex.button}
      </div>
      <p className="text-xs text-ink-muted">
        {fmtNumber(groups.length)} group{groups.length === 1 ? '' : 's'} · {fmtNumber(shownRecords)} records
        {result.groups.length < result.totalGroups && ` · the ${fmtNumber(result.groups.length)} largest groups`}
        {result.truncated && ' · from the first 20,000 records'}
      </p>
      {filtering && (
        <p className="text-xs text-ink-muted">
          Column filters on: {Object.keys(colFilters).map((c) => result.columns.find((x) => x.name === c)?.label ?? c).join(', ')} ·{' '}
          <button type="button" className="font-semibold text-brand hover:underline" onClick={() => setColFilters({})}>Clear column filters</button>
        </p>
      )}

      {groups.length === 0 ? (
        <p className="rounded-lg bg-muted/50 px-4 py-6 text-center text-sm text-ink-muted">
          {!result.totalGroups ? 'No duplicates found.' : mode === 'exact' && !term && !filtering ? 'No exact duplicates: every match here differs a little (spelling, suffix or abbreviation). Choose All or Relevant match to see them.' : 'No groups match this filter.'}
          {filtering && (
            <button type="button" className="ml-1 font-semibold text-brand hover:underline" onClick={() => setColFilters({})}>Clear column filters</button>
          )}
        </p>
      ) : (
        ex.wrap(
        <div className={cx('relative', ex.boxClass)}>
        {ex.big && (
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="text-sm font-semibold">
              Duplicates on {result.rules.map((r) => r.join(' + ')).join(' · ')}{' '}
              <span className="font-normal text-ink-muted">· {fmtNumber(groups.length)} groups shown</span>
            </p>
            {ex.button}
          </div>
        )}
        <div className={cx(ex.scrollClass('max-h-[32rem]'), 'rounded-xl border border-line')}>
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
                          <span className="w-fit rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-brand-ink ring-1 ring-brand/20">#{g.n} · {g.count}</span>
                          <span className="mt-1 text-[10px] text-ink-subtle">{g.matchedOn}</span>
                        </span>
                      )}
                    </td>
                    {result.columns.map((c, ci) => {
                      // The matched fields: red on an exact twin (Exact match) or on every record of the group (Relevant match).
                      const matched = g.cols.includes(c.name) && show(rec.values[c.name]) !== '—';
                      const others = g.records.length - 1;
                      const same =
                        flag && !flag.includes(c.name)
                          ? null
                          : matched && g.twins[ri] > 0
                            ? `Exact match with ${g.twins[ri]} other record${g.twins[ri] > 1 ? 's' : ''} in this group`
                            : matched && mode !== 'exact'
                              ? `Relevant match with ${others} other record${others > 1 ? 's' : ''} in this group`
                              : sameIn(g.records, ri, c.name, c.label, g.matchedOn);
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
        </div>,
        )
      )}
    </div>
  );
}
