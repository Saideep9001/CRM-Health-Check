import { ArrowDownRight, ArrowUpRight, Download, ExternalLink, Minus, Sparkles } from 'lucide-react';
import { findingApi } from '@/api/endpoints';
import { useFindingRecords } from '@/api/queries';
import { formatValue } from '@/components/data/format';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingState } from '@/components/ui/States';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, Finding } from '@/types';

/** How a problem changed since the previous health check. */
export function ChangeBadge({ finding, className }: { finding: Finding; className?: string }) {
  const change = finding.change ?? 'new';
  const diff = finding.previousAffected != null ? finding.affectedRecords - finding.previousAffected : 0;
  const look = {
    new: { cls: 'bg-brand-soft text-brand-ink', icon: <Sparkles className="h-3 w-3" />, text: 'New' },
    worse: { cls: 'bg-bad-soft text-bad', icon: <ArrowUpRight className="h-3 w-3" />, text: `Worse +${fmtNumber(diff)}` },
    better: { cls: 'bg-good-soft text-good', icon: <ArrowDownRight className="h-3 w-3" />, text: `Better ${fmtNumber(diff)}` },
    same: { cls: 'bg-muted text-ink-muted', icon: <Minus className="h-3 w-3" />, text: 'No change' },
  }[change];
  return (
    <span
      className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold', look.cls, className)}
      title={finding.previousAffected != null ? `${fmtNumber(finding.previousAffected)} in the previous check` : 'Not in the previous check'}
    >
      {look.icon}
      {look.text}
    </span>
  );
}

/** The exact records a problem is about, live from Salesforce, with a CSV download. */
export function AffectedRecords({ finding }: { finding: Finding }) {
  const q = useFindingRecords(finding.id, !!finding.recordsAvailable);
  const pages = q.data?.pages ?? [];
  const first = pages[0];
  const rows = pages.flatMap((p) => p.records);
  const nameCol = first?.columns.find((c) => c.type === 'string' && /name|subject|title/i.test(c.name)) ?? first?.columns.find((c) => c.type === 'string');
  const detailCols = first ? first.columns.filter((c) => c.type !== 'id' && c !== nameCol).slice(0, 3) : [];
  const asField = (c: { name: string; label: string; type: string }) => c as unknown as DataField;

  return (
    <section className="mb-5 overflow-hidden rounded-xl border border-line">
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-muted/50 px-3 py-2">
        <span className="text-sm font-semibold">Affected records</span>
        {first?.totalSize != null && <span className="rounded-full bg-surface px-2 text-[11px] tabular-nums text-ink-muted">{fmtNumber(first.totalSize)}</span>}
        <a
          href={findingApi.recordsCsvUrl(finding.id)}
          download
          className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
          title="Download these records as a spreadsheet (up to 10,000)"
        >
          <Download className="h-3.5 w-3.5" /> Download CSV
        </a>
      </header>
      {q.isLoading ? (
        <LoadingState rows={3} label="Loading records…" />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} className="py-6" />
      ) : rows.length === 0 ? (
        <p className="px-3 py-4 text-center text-xs text-ink-subtle">No matching records right now — this may already be fixed.</p>
      ) : (
        <>
          {first?.totalSize != null && first.totalSize > finding.affectedRecords && finding.name.startsWith('Duplicate') && (
            <p className="border-b border-line bg-surface px-3 py-1.5 text-[11px] text-ink-subtle">
              Shows every record in each duplicate group, including the one you’ll keep — {fmtNumber(finding.affectedRecords)} of them are extra copies.
            </p>
          )}
          <ul className="scrollbar-thin max-h-80 divide-y divide-line overflow-y-auto">
            {rows.map((r, i) => {
              const title = nameCol ? r.values[nameCol.name] : null;
              const details = detailCols
                .map((c) => formatValue(asField(c), r.values[c.name], r.refNames[c.name]))
                .filter((t) => t !== '—')
                .join(' · ');
              return (
                <li key={r.id ?? i}>
                  <a
                    href={r.id ? `${first!.recordUrlPrefix}${r.id}` : undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-center gap-3 px-3 py-2 transition hover:bg-muted"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium group-hover:text-brand">{typeof title === 'string' && title ? title : r.id}</span>
                      {details && <span className="block truncate text-xs text-ink-subtle">{details}</span>}
                    </span>
                    <ExternalLink className="h-3.5 w-3.5 shrink-0 text-ink-subtle opacity-0 transition group-hover:opacity-100" />
                  </a>
                </li>
              );
            })}
          </ul>
          {q.hasNextPage && (
            <div className="border-t border-line p-2 text-center">
              <Button size="sm" variant="ghost" disabled={q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>
                {q.isFetchingNextPage ? 'Loading…' : `Show more (${fmtNumber(rows.length)} of ${fmtNumber(first?.totalSize ?? rows.length)})`}
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
