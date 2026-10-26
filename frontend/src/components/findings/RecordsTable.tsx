import type { InfiniteData, UseInfiniteQueryResult } from '@tanstack/react-query';
import { AlertTriangle, Download, ExternalLink, Search, X } from 'lucide-react';
import { useState } from 'react';
import { useDataObject } from '@/api/queries';
import { ColumnFilter, columnFilter, type ValuesSource } from '@/components/data/ColumnFilter';
import { formatValue } from '@/components/data/format';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingState } from '@/components/ui/States';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, DataFilter, FindingRecordsPage } from '@/types';

/** The engine's own cleaning (backend/app/engine/data_quality.py → norm_company / norm_website), to band duplicate groups. */
const COMPANY_WORDS = /\b(the|incorporated|inc|llc|llp|ltd|limited|corp|corporation|co|company|plc|gmbh|ag|pvt|private|pty|sa|srl|bv)\b/g;
function matchKey(v: unknown, field: string): string {
  const s = String(v ?? '').trim().toLowerCase();
  if (!s) return '';
  if (/website|url|domain/i.test(field)) return s.replace(/^[a-z]+:\/\//, '').replace(/^www\d?\./, '').split(/[/?#:]/)[0].replace(/^\.+|\.+$/g, '');
  if (/email/i.test(field)) return s;
  return s.replace(/&/g, ' and ').replace(/[^a-z0-9 ]/g, ' ').replace(COMPANY_WORDS, ' ').replace(/\s+/g, ' ').trim();
}

/** Records live from Salesforce as a real table; the columns that explain the result come first; rows open in Salesforce.
 *  `grouped` bands rows that share the sorted-by value (duplicate groups) and numbers each group. */
export function RecordsTable({
  query,
  csvUrl,
  title = 'Records',
  empty = 'No matching records right now — this may already be fixed.',
  grouped,
  filters = [],
  onFiltersChange,
  valuesSource,
  keyFields,
}: {
  query: UseInfiniteQueryResult<InfiniteData<FindingRecordsPage, unknown>, Error>;
  csvUrl?: string;
  title?: string;
  empty?: string;
  grouped?: boolean;
  /** Excel-style column filters (applied by the server to all the records, not just the loaded ones). */
  filters?: DataFilter[];
  onFiltersChange?: (next: DataFilter[]) => void;
  /** Where a column's filter values come from (this measure's or problem's records). */
  valuesSource?: ValuesSource;
  /** Key fields (Missing Key Fields): an empty one is marked on its cell. */
  keyFields?: string[];
}) {
  const pages = query.data?.pages ?? [];
  const first = pages[0];
  // Which columns can be filtered: from the object's field list (cached; Your Data uses the same).
  const describe = useDataObject(onFiltersChange ? (first?.object ?? undefined) : undefined);
  const fieldOf = (name: string) => describe.data?.fields.find((f) => f.name === name);
  const setColumn = (col: string, f: DataFilter | null) => {
    const rest = filters.filter((x) => x !== columnFilter(filters, col));
    onFiltersChange?.(f ? [...rest, f] : rest);
  };
  // Duplicate groups: rows with the same cleaned value of the matched field, kept together.
  const groupCol = grouped ? first?.sortedBy ?? null : null;
  const [filter, setFilter] = useState('');
  const term = filter.trim().toLowerCase();
  // Filter the loaded records by any value (name, email, city, owner…).
  const loaded = pages
    .flatMap((p) => p.records)
    .filter((r) => !term || [...Object.values(r.values), ...Object.values(r.refNames)].some((v) => v != null && String(v).toLowerCase().includes(term)));
  const rows = groupCol
    ? [...loaded].sort((a, b) => matchKey(a.values[groupCol], groupCol).localeCompare(matchKey(b.values[groupCol], groupCol)))
    : loaded;
  // The server lists the columns that explain the result first (e.g. Name, Website for duplicates).
  const cols = first ? first.columns.filter((c) => c.type !== 'id').slice(0, 8) : [];
  const asField = (c: { name: string; label: string; type: string }) => c as unknown as DataField;
  // Why each flagged value was flagged, from the check (record id → field → reason), across the loaded pages.
  const notes: Record<string, Record<string, string>> = Object.assign({}, ...pages.map((p) => p.cellNotes ?? {}));
  const key = new Set(keyFields ?? []);
  const why = (r: { id?: string | null; values: Record<string, unknown> }, field: string): string | null => {
    const n = r.id ? notes[r.id]?.[field] : undefined;
    if (n) return n;
    const val = r.values[field];
    return key.has(field) && (val == null || String(val).trim() === '') ? 'Empty — key field' : null;
  };
  const flagged = rows.some((r) => cols.some((c) => why(r, c.name)));

  const groupOf: number[] = [];
  const groupSize = new Map<number, number>();
  if (groupCol) {
    let g = 0;
    let prev = '\u0000';
    rows.forEach((r) => {
      const k = matchKey(r.values[groupCol], groupCol);
      if (k !== prev) {
        g += 1;
        prev = k;
      }
      groupOf.push(g);
      groupSize.set(g, (groupSize.get(g) ?? 0) + 1);
    });
  }

  return (
    <section className="overflow-hidden rounded-xl border border-line">
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-muted/50 px-3 py-2">
        <span className="text-sm font-semibold">{title}</span>
        <span className="relative ml-2 min-w-0 flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
          <input className="input h-7 pl-7 text-xs" placeholder="Filter by any value…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter records" />
        </span>
        {first?.totalSize != null && (
          <span className={cx('rounded-full px-2 text-[11px] tabular-nums', filters.length ? 'bg-brand-soft font-semibold text-brand-ink' : 'bg-surface text-ink-muted')}>
            {fmtNumber(first.totalSize)}
            {filters.length ? ' match' : ''}
          </span>
        )}
        {csvUrl && (
          <a href={csvUrl} download className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline" title="Download these records as a spreadsheet (up to 10,000)">
            <Download className="h-3.5 w-3.5" /> Download CSV
          </a>
        )}
      </header>
      {filters.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-line bg-brand-soft/30 px-3 py-1.5">
          <span className="text-[11px] font-medium text-ink-muted">Filtered:</span>
          {filters.map((f, i) => (
            <span key={`${f.field}-${i}`} className="inline-flex items-center gap-1 rounded-full border border-brand/30 bg-surface px-2 py-0.5 text-[11px]">
              {f.label ?? f.field}
              <button type="button" onClick={() => onFiltersChange?.(filters.filter((_, j) => j !== i))} className="text-ink-subtle hover:text-bad" aria-label={`Remove filter ${f.label ?? f.field}`}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <button type="button" onClick={() => onFiltersChange?.([])} className="ml-1 text-[11px] font-semibold text-brand hover:underline">
            Clear all
          </button>
        </div>
      )}
      {query.isLoading ? (
        <LoadingState rows={4} label="Loading records from Salesforce…" />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} className="py-6" />
      ) : rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-ink-subtle">
          {term ? `No loaded records match “${filter}”.` : filters.length ? 'No records match these column filters.' : empty}
        </p>
      ) : (
        <>
          <div className="scrollbar-thin max-h-[26rem] overflow-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
                <tr>
                  {groupCol && <th className="whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">Group</th>}
                  {cols.map((c) => {
                    const meta = fieldOf(c.name);
                    const filtered = !!columnFilter(filters, c.name);
                    return (
                      <th
                        key={c.name}
                        className={cx(
                          'whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide',
                          filtered ? 'bg-brand-soft text-brand-ink shadow-[inset_0_-2px_0_rgb(var(--brand))]' : 'text-ink-subtle',
                        )}
                      >
                        <span className="inline-flex items-center">
                          {c.type === 'reference' ? c.label.replace(/ ID$/, '') : c.label}
                          {onFiltersChange && first && meta?.groupable && meta.filterable && meta.type !== 'id' && (
                            <ColumnFilter object={first.object} field={meta} search="" filters={filters} onApply={(f) => setColumn(c.name, f)} source={valuesSource} />
                          )}
                        </span>
                      </th>
                    );
                  })}
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((r, i) => {
                  const href = r.id ? `${first!.recordUrlPrefix}${r.id}` : undefined;
                  return (
                    <tr
                      key={r.id ?? i}
                      className={cx('group hover:bg-muted/60', groupCol && groupOf[i] % 2 === 0 && 'bg-brand-soft/30', groupCol && i > 0 && groupOf[i] !== groupOf[i - 1] && 'border-t-2 border-t-brand/20')}
                    >
                      {groupCol && (
                        <td className="whitespace-nowrap px-3 py-2">
                          {(i === 0 || groupOf[i] !== groupOf[i - 1]) && (
                            <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-brand-ink ring-1 ring-brand/20">
                              #{groupOf[i]} · {groupSize.get(groupOf[i])}
                            </span>
                          )}
                        </td>
                      )}
                      {cols.map((c, ci) => {
                        const v = formatValue(asField(c), r.values[c.name], r.refNames[c.name]);
                        const reason = why(r, c.name);
                        return (
                          <td
                            key={c.name}
                            className={cx('max-w-[16rem] truncate px-3 py-2', reason ? 'bg-bad-soft/60' : columnFilter(filters, c.name) && 'bg-brand-soft/40')}
                            title={reason ? `${v === '—' ? 'Empty' : v}
Why it’s flagged: ${reason}` : v}
                          >
                            {ci === 0 && href ? (
                              <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium text-ink hover:text-brand hover:underline">
                                {v === '—' ? r.id : v}
                              </a>
                            ) : (
                              <span className={v === '—' ? 'text-ink-subtle' : ''}>{v}</span>
                            )}
                            {reason && (
                              <span className="mt-0.5 flex min-w-[11rem] items-start gap-1 whitespace-normal text-[10.5px] font-medium leading-snug text-bad">
                                <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
                                {reason}
                              </span>
                            )}
                          </td>
                        );
                      })}
                      <td className="px-2">
                        {href && (
                          <a href={href} target="_blank" rel="noopener noreferrer" aria-label="Open in Salesforce" className="text-ink-subtle opacity-0 transition hover:text-brand group-hover:opacity-100">
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {flagged && (
            <p className="flex items-center gap-1 border-t border-line bg-bad-soft/30 px-3 py-1.5 text-[11px] text-ink-muted">
              <AlertTriangle className="h-3 w-3 text-bad" /> Red cells are the values this check flagged; the line under each says why. Hover a cell for the full reason.
            </p>
          )}
          {query.hasNextPage && (
            <div className="border-t border-line p-2 text-center">
              <Button size="sm" variant="ghost" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
                {query.isFetchingNextPage ? 'Loading…' : `Show more (${fmtNumber(rows.length)} of ${fmtNumber(first?.totalSize ?? rows.length)})`}
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
