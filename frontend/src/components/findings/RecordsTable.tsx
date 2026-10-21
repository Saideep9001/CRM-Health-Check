import type { InfiniteData, UseInfiniteQueryResult } from '@tanstack/react-query';
import { Download, ExternalLink } from 'lucide-react';
import { formatValue } from '@/components/data/format';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingState } from '@/components/ui/States';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, FindingRecordsPage } from '@/types';

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
}: {
  query: UseInfiniteQueryResult<InfiniteData<FindingRecordsPage, unknown>, Error>;
  csvUrl?: string;
  title?: string;
  empty?: string;
  grouped?: boolean;
}) {
  const pages = query.data?.pages ?? [];
  const first = pages[0];
  // Duplicate groups: rows with the same cleaned value of the matched field, kept together.
  const groupCol = grouped ? first?.sortedBy ?? null : null;
  const loaded = pages.flatMap((p) => p.records);
  const rows = groupCol
    ? [...loaded].sort((a, b) => matchKey(a.values[groupCol], groupCol).localeCompare(matchKey(b.values[groupCol], groupCol)))
    : loaded;
  // The server lists the columns that explain the result first (e.g. Name, Website for duplicates).
  const cols = first ? first.columns.filter((c) => c.type !== 'id').slice(0, 8) : [];
  const asField = (c: { name: string; label: string; type: string }) => c as unknown as DataField;

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
        {first?.totalSize != null && <span className="rounded-full bg-surface px-2 text-[11px] tabular-nums text-ink-muted">{fmtNumber(first.totalSize)}</span>}
        {csvUrl && (
          <a href={csvUrl} download className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline" title="Download these records as a spreadsheet (up to 10,000)">
            <Download className="h-3.5 w-3.5" /> Download CSV
          </a>
        )}
      </header>
      {query.isLoading ? (
        <LoadingState rows={4} label="Loading records from Salesforce…" />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} className="py-6" />
      ) : rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-ink-subtle">{empty}</p>
      ) : (
        <>
          <div className="scrollbar-thin max-h-[26rem] overflow-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
                <tr>
                  {groupCol && <th className="whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">Group</th>}
                  {cols.map((c) => (
                    <th key={c.name} className="whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">{c.type === 'reference' ? c.label.replace(/ ID$/, '') : c.label}</th>
                  ))}
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
                        return (
                          <td key={c.name} className="max-w-[16rem] truncate px-3 py-2" title={v}>
                            {ci === 0 && href ? (
                              <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium text-ink hover:text-brand hover:underline">
                                {v === '—' ? r.id : v}
                              </a>
                            ) : (
                              <span className={v === '—' ? 'text-ink-subtle' : ''}>{v}</span>
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
