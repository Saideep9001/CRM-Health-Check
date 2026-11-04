import { RecordLink } from '@/components/data/RecordLink';
import type { InfiniteData, UseInfiniteQueryResult } from '@tanstack/react-query';
import { AlertTriangle, Download, ExternalLink, Search, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useDataObject } from '@/api/queries';
import { ColumnFilter, columnFilter, type ValuesSource } from '@/components/data/ColumnFilter';
import { formatValue } from '@/components/data/format';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingState } from '@/components/ui/States';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, DataFilter, FindingRecordsPage } from '@/types';
import { useExpand } from '@/components/ui/Expand';

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
  markOnly,
  toolbar,
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
  /** When fields are picked in the page's selector: only their cells are marked. */
  markOnly?: string[];
  /** Extra controls in the header, after the count (e.g. the No Activity period). */
  toolbar?: ReactNode;
}) {
  const ex = useExpand();
  const pages = query.data?.pages ?? [];
  const first = pages[0];
  // Which columns can be filtered: from the object's field list (cached; Your Data uses the same).
  const describe = useDataObject(onFiltersChange ? (first?.object ?? undefined) : undefined);
  const fieldOf = (name: string) => describe.data?.fields.find((f) => f.name === name);
  const setColumn = (col: string, f: DataFilter | null) => {
    const rest = filters.filter((x) => x !== columnFilter(filters, col));
    onFiltersChange?.(f ? [...rest, f] : rest);
  };
  // Rows kept together: duplicate groups (the same cleaned value of the matched field), or records grouped by their
  // Account (the server sorts them by Account name), with the Account named first in each block.
  const byAccount = first?.sortedBy === 'AccountId';
  const groupCol = byAccount ? 'AccountId' : grouped ? first?.sortedBy ?? null : null;
  const [filter, setFilter] = useState('');
  const term = filter.trim().toLowerCase();
  // Filter the loaded records by any value (name, email, city, owner…).
  const loaded = pages
    .flatMap((p) => p.records)
    .filter((r) => !term || [...Object.values(r.values), ...Object.values(r.refNames)].some((v) => v != null && String(v).toLowerCase().includes(term)));
  const rows = groupCol && !byAccount // by Account: already sorted by the Account's name on the server
    ? [...loaded].sort((a, b) => matchKey(a.values[groupCol], groupCol).localeCompare(matchKey(b.values[groupCol], groupCol)))
    : loaded;
  // The server lists the columns that explain the result first (e.g. Name, Website for duplicates).
  const shown = first ? first.columns.filter((c) => c.type !== 'id' && !(byAccount && c.name === 'AccountId')) : []; // the Account heads its block
  // Frozen columns (e.g. Roles on Open Deals) go last and stay in view on the right while the table scrolls sideways.
  const frozen = shown.filter((c) => c.frozen);
  const cols = [...shown.filter((c) => !c.frozen).slice(0, 12 - frozen.length), ...frozen];
  const hasFrozen = frozen.length > 0;
  const stick = 'sticky right-8 z-[1] bg-surface shadow-[-6px_0_8px_-6px_rgb(0_0_0/0.18)]';
  const asField = (c: { name: string; label: string; type: string }) => c as unknown as DataField;
  // Why each flagged value was flagged, from the check (record id → field → reason), across the loaded pages.
  const notes: Record<string, Record<string, string>> = Object.assign({}, ...pages.map((p) => p.cellNotes ?? {}));
  const key = new Set(keyFields ?? []);
  const why = (r: { id?: string | null; values: Record<string, unknown> }, field: string, row?: number): string | null => {
    if (markOnly?.length && !markOnly.includes(field)) return null;
    const same = row != null ? dupNote[row]?.[field] : undefined; // duplicate groups: a value another record in the group shares
    if (same) return same;
    const n = r.id ? notes[r.id]?.[field] : undefined;
    if (n) return n;
    const val = r.values[field];
    return key.has(field) && (val == null || String(val).trim() === '') ? 'Empty — key field' : null;
  };
  const groupOf: number[] = [];
  const groupSize = new Map<number, number>();
  if (groupCol) {
    let g = 0;
    let prev = '\u0000';
    rows.forEach((r) => {
      const k = byAccount ? String(r.values.AccountId ?? '') : matchKey(r.values[groupCol], groupCol);
      if (k !== prev) {
        g += 1;
        prev = k;
      }
      groupOf.push(g);
      groupSize.set(g, (groupSize.get(g) ?? 0) + 1);
    });
  }
  // In each duplicate group, the values the records share (compared the engine's way) are marked, with how many share them.
  const dupNote: Record<string, string>[] = [];
  if (groupCol && grouped) {
    // Picklists (Stage, Type, Industry…) are shared by design, so they're never what makes a duplicate.
    const compared = cols.filter((c) => !['reference', 'date', 'datetime', 'boolean', 'id', 'int', 'double', 'currency', 'percent', 'picklist', 'multipicklist'].includes(c.type));
    const members = new Map<number, number[]>();
    groupOf.forEach((g, i) => members.set(g, [...(members.get(g) ?? []), i]));
    for (const [g, idx] of members) {
      if (idx.length < 2) continue;
      for (const c of compared) {
        const keys = idx.map((i) => matchKey(rows[i].values[c.name], c.name));
        idx.forEach((i, n) => {
          const others = keys[n] ? keys.filter((k, m) => m !== n && k === keys[n]).length : 0;
          if (others) (dupNote[i] ??= {})[c.name] = `Same as ${others} other record${others > 1 ? 's' : ''} in group #${g}`;
        });
      }
    }
  }
  const flagged = rows.some((r, i) => cols.some((c) => why(r, c.name, i)));

  return ex.wrap(
    <section className={cx('overflow-hidden rounded-xl border border-line', ex.boxClass)}>
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
        {toolbar}
        {csvUrl && (
          <a href={csvUrl} download className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline" title="Download these records as a spreadsheet (up to 10,000)">
            <Download className="h-3.5 w-3.5" /> Download CSV
          </a>
        )}
        <span className={cx(!csvUrl && 'ml-auto')}>{ex.button}</span>
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
          <div className={ex.scrollClass('max-h-[26rem]')}>
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
                <tr>
                  {groupCol && <th className="whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">{byAccount ? 'Account' : 'Group'}</th>}
                  {cols.map((c) => {
                    const meta = fieldOf(c.name);
                    const filtered = !!columnFilter(filters, c.name);
                    return (
                      <th
                        key={c.name}
                        className={cx(
                          'whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide',
                          c.frozen && stick,
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
                  <th className={cx('w-8', hasFrozen && 'sticky right-0 z-[1] bg-surface')} />
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
                        <td className={cx('px-3 py-2', byAccount ? 'max-w-[14rem] align-top' : 'whitespace-nowrap')}>
                          {(i === 0 || groupOf[i] !== groupOf[i - 1]) &&
                            (byAccount ? (
                              <span className="block">
                                <span className="block truncate font-semibold text-ink" title={r.refNames.AccountId ?? undefined}>
                                  {r.refNames.AccountId ?? (r.values.AccountId ? String(r.values.AccountId) : 'No Account')}
                                </span>
                                <span className="text-[11px] text-ink-muted">{fmtNumber(groupSize.get(groupOf[i]) ?? 0)} record{groupSize.get(groupOf[i]) === 1 ? '' : 's'}</span>
                              </span>
                            ) : (
                              <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-brand-ink ring-1 ring-brand/20">
                                #{groupOf[i]} · {groupSize.get(groupOf[i])}
                              </span>
                            ))}
                        </td>
                      )}
                      {cols.map((c, ci) => {
                        const v = formatValue(asField(c), r.values[c.name], r.refNames[c.name]);
                        const reason = why(r, c.name, i);
                        if (c.type === 'lines') {
                          // several values in one cell (e.g. a Contact's Accounts): one per line, like rows within the row
                          const lines = v === '—' ? [] : v.split('\n');
                          return (
                            <td key={c.name} className={cx('max-w-[18rem] px-3 py-1 align-top', c.frozen && cx(stick, 'min-w-[16rem] group-hover:bg-muted'))}>
                              {lines.length ? (
                                <ul className="divide-y divide-line">
                                  {lines.map((line, li) => (
                                    <li key={li} className="truncate py-1" title={line}>{line}</li>
                                  ))}
                                </ul>
                              ) : (
                                <span className="text-ink-subtle">—</span>
                              )}
                            </td>
                          );
                        }
                        return (
                          <td
                            key={c.name}
                            className={cx('max-w-[16rem] truncate px-3 py-2 align-top', reason ? 'bg-bad-soft/60' : columnFilter(filters, c.name) && 'bg-brand-soft/40')}
                            title={reason ? `${v === '—' ? 'Empty' : v}
Why it’s flagged: ${reason}` : v}
                          >
                            {ci === 0 && href ? (
                              <RecordLink object={first!.object} id={r.id!}>{v === '—' ? r.id : v}</RecordLink>
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
                      <td className={cx('px-2', hasFrozen && 'sticky right-0 z-[1] w-8 bg-surface group-hover:bg-muted')}>
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
    </section>,
  );
}
