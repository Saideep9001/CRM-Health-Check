import { CheckCircle2, ExternalLink, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { ColumnFilter, columnFilter, type ValuesSource } from '@/components/data/ColumnFilter';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, DataFilter, FieldListItem } from '@/types';

/** What each column filters on (worked out from the list itself, so filtering needs no server). */
const filledBand = (f: FieldListItem) => {
  if (f.pct == null || f.filled == null || !f.of) return 'Can’t be counted';
  const exact = (100 * f.filled) / f.of; // not the rounded %: 0.99% is under 1%, as the check counts it
  return f.filled === 0 ? 'Never filled in' : exact < 1 ? 'Under 1%' : exact < 20 ? '1% to 20%' : '20% or more';
};
const whyListed = (f: FieldListItem) => (/^Filled on only/.test(f.note) ? 'Filled on only a few records' : f.note || null);
const COLUMNS: { name: string; label: string; get: (f: FieldListItem) => string | null }[] = [
  { name: 'kind', label: 'Custom or standard', get: (f) => (f.custom ? 'Custom' : 'Standard') },
  { name: 'type', label: 'Type', get: (f) => f.type || null },
  { name: 'filled', label: 'Filled in', get: filledBand },
  { name: 'note', label: 'Why it’s listed', get: whyListed },
];
const column = (name: string) => COLUMNS.find((c) => c.name === name)!;
const asField = (name: string) => ({ name, label: column(name).label, type: 'string', groupable: true, filterable: true }) as unknown as DataField;

function keeps(f: FieldListItem, filter: DataFilter): boolean {
  const v = column(filter.field)?.get(f) ?? null;
  if (filter.op === 'blank') return v == null;
  const named = (filter.value as unknown[]) ?? [];
  return filter.op === 'in' ? named.includes(v) : !named.includes(v);
}

/** The fields behind a card about fields (unused, outdated, look-alike…): fill rate and why each is listed, with
 *  Excel-style filters on Custom/standard, Type, Filled in and Why it's listed. */
/** Which of a look-alike pair to keep: the one filled on more records; if even, the standard Salesforce field; then the one
 *  on more record type layouts. */
function keepOf(a: FieldListItem, b: FieldListItem, rtsOf: (f: string) => string[]): { keep: FieldListItem; why: string } {
  const pct = (f: FieldListItem) => (f.pct == null ? null : `${f.pct % 1 ? f.pct.toFixed(1) : f.pct}%`);
  if (a.filled != null && b.filled != null && a.filled !== b.filled) {
    const [hi, lo] = a.filled > b.filled ? [a, b] : [b, a];
    const recs = (n: number) => `${fmtNumber(n)} record${n === 1 ? '' : 's'}`;
    return { keep: hi, why: `filled on ${recs(hi.filled!)} (${pct(hi)}), the other on ${recs(lo.filled!)} (${pct(lo)})` };
  }
  if (a.custom !== b.custom) return { keep: a.custom ? b : a, why: 'it’s Salesforce’s standard field (used by reports, apps and integrations)' };
  const [ra, rb] = [rtsOf(a.name).length, rtsOf(b.name).length];
  if (ra !== rb) return ra > rb ? { keep: a, why: `it’s on ${ra} record type layouts, the other on ${rb}` } : { keep: b, why: `it’s on ${rb} record type layouts, the other on ${ra}` };
  // Even on every count: either works, so both rows name the same one (the simpler API name).
  const [first] = [a, b].sort((x, y) => x.name.length - y.name.length || x.name.localeCompare(y.name));
  return { keep: first, why: 'both are used the same way, so either works; this one has the simpler API name — move the other’s values into it' };
}

export function FieldListTable({
  items,
  id = '',
  all,
  recordTypesOf,
  linkOf,
}: {
  items: FieldListItem[];
  id?: string;
  /** Every field of the card (look-alike partners may be outside the record type picked). */
  all?: FieldListItem[];
  /** The record types whose page layout has the field (empty: none). */
  recordTypesOf?: (field: string) => string[];
  /** The field's page in Salesforce Setup. */
  linkOf?: (field: string) => string | undefined;
}) {
  const rtsOf = recordTypesOf ?? (() => []);
  const onText = (f: string) => {
    if (!recordTypesOf) return null;
    const r = rtsOf(f);
    return r.length ? `On ${r.slice(0, 3).join(', ')}${r.length > 3 ? ` +${r.length - 3}` : ''}` : 'On no record type’s layout';
  };
  const open = (f: string, text = 'Open in Salesforce') => {
    const url = linkOf?.(f);
    return url ? (
      <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[11px] font-medium text-brand hover:underline">
        {text} <ExternalLink className="h-3 w-3" />
      </a>
    ) : null;
  };
  const byName = new Map((all ?? items).map((f) => [f.name, f]));
  const fillText = (f: FieldListItem) => (f.pct == null ? 'can’t be counted' : `filled on ${f.pct % 1 ? f.pct.toFixed(1) : f.pct}%`);
  // "Looks like Label (ApiName)": the pair, which one to keep and why, with links to both.
  const lookalike = (f: FieldListItem) => {
    const other = byName.get(f.note.match(/\(([^()]+)\)$/)?.[1] ?? '');
    if (!other) return <span className="text-ink-muted">{f.note}</span>;
    const { keep, why } = keepOf(f, other, rtsOf);
    const keepThis = keep.name === f.name;
    return (
      <span className="block space-y-1">
        <span className="block text-ink">
          Looks like <span className="font-semibold">{other.label}</span> <span className="font-mono text-[11px] text-ink-subtle">{other.name}</span>
          {other.custom ? '' : ' (standard)'}
        </span>
        <span className="block text-[11px] text-ink-muted">
          That one is {fillText(other)}
          {recordTypesOf ? ` · ${onText(other.name)}` : ''}
        </span>
        <span className={cx('flex items-start gap-1 text-[11px] font-medium', keepThis ? 'text-good' : 'text-warn')}>
          <CheckCircle2 className="mt-px h-3 w-3 shrink-0" />
          <span>
            {keepThis ? 'Keep this one' : `Keep ${other.label} (${other.name}) instead`} — {why}.
          </span>
        </span>
        <span className="flex flex-wrap gap-3">{open(other.name, `Open ${other.label}`)}</span>
      </span>
    );
  };
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<DataFilter[]>([]);
  const term = query.trim().toLowerCase();
  const rows = items.filter(
    (f) => (!term || `${f.label} ${f.name} ${f.type} ${f.note}`.toLowerCase().includes(term)) && filters.every((x) => keeps(f, x)),
  );
  const notes = items.some((f) => f.note);
  // Each column's values and how many fields have each, among the fields the other filters keep.
  const source: ValuesSource = useMemo(
    () => ({
      key: ['field-list', id, items.length],
      load: async (name, others) => {
        const kept = items.filter((f) => others.every((x) => keeps(f, x)));
        const counts = new Map<string, number>();
        let blanks = 0;
        for (const f of kept) {
          const v = column(name).get(f);
          if (v == null) blanks += 1;
          else counts.set(v, (counts.get(v) ?? 0) + 1);
        }
        const values = [...counts].map(([value, count]) => ({ value, label: value, count })).sort((a, b) => b.count - a.count);
        return { field: name, values, blanks, truncated: false };
      },
    }),
    [items, id],
  );
  const setColumn = (name: string, f: DataFilter | null) => {
    const rest = filters.filter((x) => x !== columnFilter(filters, name));
    setFilters(f ? [...rest, f] : rest);
  };
  const filterOn = (name: string) => (
    <ColumnFilter object="" field={asField(name)} search="" filters={filters} onApply={(f) => setColumn(name, f)} source={source} />
  );
  const head = (name: string, label: string, className = '') => (
    <th className={cx('px-3 py-2', className, columnFilter(filters, name) && 'bg-brand-soft text-brand-ink')}>
      <span className="inline-flex items-center">
        {label}
        {filterOn(name)}
      </span>
    </th>
  );

  if (!items.length) return <p className="rounded-lg bg-good-soft/50 px-4 py-6 text-center text-sm text-good">No fields to list — nothing was found here.</p>;
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-muted/40 px-3 py-2">
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
          <input className="input h-8 pl-8 text-xs" placeholder="Filter fields…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <span className={cx('rounded-full px-2 text-[11px] tabular-nums', term || filters.length ? 'bg-brand-soft font-semibold text-brand-ink' : 'text-ink-muted')}>
          {term || filters.length ? `${fmtNumber(rows.length)} of ${fmtNumber(items.length)} fields` : `${fmtNumber(items.length)} fields`}
        </span>
      </div>
      {filters.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-line bg-brand-soft/30 px-3 py-1.5">
          <span className="text-[11px] font-medium text-ink-muted">Filtered:</span>
          {filters.map((f, i) => (
            <span key={`${f.field}-${i}`} className="inline-flex items-center gap-1 rounded-full border border-brand/30 bg-surface px-2 py-0.5 text-[11px]">
              {f.label ?? f.field}
              <button type="button" onClick={() => setFilters(filters.filter((_, j) => j !== i))} className="text-ink-subtle hover:text-bad" aria-label={`Remove filter ${f.label ?? f.field}`}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <button type="button" onClick={() => setFilters([])} className="ml-1 text-[11px] font-semibold text-brand hover:underline">
            Clear all
          </button>
        </div>
      )}
      <div className="scrollbar-thin max-h-[32rem] overflow-auto">
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead className="sticky top-0 z-10 bg-surface text-[11px] uppercase tracking-wide text-ink-subtle shadow-[0_1px_0_rgb(var(--line))]">
            <tr>
              {head('kind', 'Field')}
              {head('type', 'Type')}
              {head('filled', 'Filled in', 'w-56')}
              {notes && head('note', 'Why it’s listed')}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.length === 0 && (
              <tr>
                <td colSpan={notes ? 4 : 3} className="px-3 py-6 text-center text-ink-subtle">
                  No fields match these filters.
                </td>
              </tr>
            )}
            {rows.map((f, i) => (
              <tr key={`${f.name}-${i}`} className="hover:bg-muted/50">
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1.5 font-medium text-ink">
                    {f.label}
                    {f.custom && <span className="rounded bg-brand-soft px-1.5 py-px text-[10px] font-semibold text-brand-ink">Custom</span>}
                  </span>
                  <span className="font-mono text-[11px] text-ink-subtle">{f.name}</span>
                  {recordTypesOf && <span className="block text-[11px] text-ink-subtle">{onText(f.name)}</span>}
                  {open(f.name)}
                </td>
                <td className="px-3 py-2 text-ink-muted">{f.type}</td>
                <td className="px-3 py-2">
                  {f.pct == null ? (
                    <span className="text-ink-subtle">Can’t be counted</span>
                  ) : (
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                        <span
                          className={cx('block h-full rounded-full', f.pct < 1 ? 'bg-bad' : f.pct < 20 ? 'bg-warn' : 'bg-good')}
                          style={{ width: `${Math.max(f.pct, f.filled ? 2 : 0)}%` }}
                        />
                      </span>
                      <span className="tabular-nums text-ink">{f.pct % 1 ? f.pct.toFixed(1) : f.pct}%</span>
                      <span className="tabular-nums text-ink-subtle">
                        {fmtNumber(f.filled ?? 0)} of {fmtNumber(f.of ?? 0)}
                      </span>
                    </span>
                  )}
                </td>
                {notes && <td className="px-3 py-2 align-top text-ink-muted">{/^Looks like /.test(f.note) ? lookalike(f) : f.note}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
