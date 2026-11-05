import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Route } from 'lucide-react';
import { indicatorApi, type SalesPathData } from '@/api/endpoints';
import { InfoTip } from '@/components/ui/HelpTip';
import { cx } from '@/lib/format';

/** One stage's guidance as Salesforce has it: plain lines, with "• " lines shown as a list. */
function Guidance({ lines }: { lines: string[] }) {
  const blocks: (string | string[])[] = [];
  for (const line of lines) {
    if (line.startsWith('• ')) {
      const last = blocks[blocks.length - 1];
      if (Array.isArray(last)) last.push(line.slice(2));
      else blocks.push([line.slice(2)]);
    } else blocks.push(line);
  }
  return (
    <div className="space-y-1">
      {blocks.map((b, i) =>
        Array.isArray(b) ? (
          <ul key={i} className="list-disc space-y-0.5 pl-5">
            {b.map((item, j) => (
              <li key={j}>{item}</li>
            ))}
          </ul>
        ) : (
          <p key={i}>{b}</p>
        ),
      )}
    </div>
  );
}

/** Sales stage guidance gaps: the org's Opportunity Sales Paths (green = active, red = inactive). Picking one shows every
 *  stage of its sales process with its "Guidance for Success" and key fields, read live from Salesforce Setup. */
export function SalesPaths({ assessmentId }: { assessmentId: string }) {
  const data = useQuery({
    queryKey: ['sales-paths', assessmentId],
    queryFn: ({ signal }) => indicatorApi.salesPaths(assessmentId, signal),
    staleTime: 60_000,
  });
  const list: SalesPathData[] = data.data ?? [];
  const [picked, setPicked] = useState<string | undefined>();
  useEffect(() => {
    if (list.length && !list.some((p) => p.id === picked)) setPicked(list[0].id);
  }, [list, picked]);
  const path = list.find((p) => p.id === picked);

  if (data.isLoading) return <p className="text-sm text-ink-subtle">Reading the Sales Paths from Salesforce…</p>;
  if (data.error)
    return <p className="rounded-lg bg-bad-soft/50 px-4 py-3 text-sm text-bad">Couldn’t read the Sales Paths: {(data.error as Error).message}</p>;
  if (!list.length)
    return (
      <p className="rounded-lg bg-muted/50 px-4 py-3 text-sm text-ink-muted">
        No Sales Paths for Opportunities in Setup, so reps get no on-screen guidance at any stage.
      </p>
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Sales Paths">
        <span className="mr-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
          <Route className="h-3.5 w-3.5" /> Sales Paths
          <InfoTip label="About Sales Paths">
            The Opportunity Paths in Setup. Green: active. Red: inactive. Pick one to see each stage of its sales process with the guidance reps see.
          </InfoTip>
        </span>
        {list.map((p) => {
          const on = p.id === picked;
          return (
            <button
              key={p.id}
              type="button"
              aria-pressed={on}
              onClick={() => setPicked(p.id)}
              title={`${p.active ? 'Active' : 'Inactive'} · ${p.guided} of ${p.openStages} open stages have guidance`}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition',
                p.active ? 'border-good/40 bg-good-soft text-good' : 'border-bad/40 bg-bad-soft text-bad',
                on ? 'font-semibold ring-2 ring-brand ring-offset-1' : 'hover:brightness-95',
              )}
            >
              <span className={cx('h-1.5 w-1.5 rounded-full', p.active ? 'bg-good' : 'bg-bad')} aria-hidden="true" />
              {p.name}
              <span className="rounded-full bg-surface/70 px-1.5 tabular-nums">
                {p.guided}/{p.openStages}
              </span>
            </button>
          );
        })}
      </div>

      {path && (
        <div className="overflow-hidden rounded-xl border border-line">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-muted/40 px-4 py-2.5 text-xs text-ink-muted">
            <span className="text-sm font-semibold text-ink">{path.name}</span>
            <span className={cx('rounded-full px-2 py-0.5 font-medium', path.active ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
              {path.active ? 'Active' : 'Inactive'}
            </span>
            {path.salesProcess && <span>Sales Process: <span className="font-medium text-ink">{path.salesProcess}</span></span>}
            {path.recordType && <span>Record Type: <span className="font-medium text-ink">{path.recordType}</span></span>}
            <span>{path.guided} of {path.openStages} open stages have guidance</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted/30 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                <tr>
                  <th className="w-52 px-4 py-2">Opportunity Stage</th>
                  <th className="w-36 px-4 py-2">Guidance</th>
                  <th className="px-4 py-2">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {path.stages.map((s) => (
                  <tr key={s.apiName} className="align-top">
                    <td className="px-4 py-3 font-medium">
                      {s.stage}
                      {s.closed && <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-normal text-ink-subtle">Closed</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium', s.available ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
                        {s.available ? 'Available' : 'Not available'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink-muted">
                      {s.details.length ? <Guidance lines={s.details} /> : <span className="text-ink-subtle">No guidance for this stage on the Path.</span>}
                      {s.keyFields.length > 0 && (
                        <p className="mt-1.5 text-[11px] text-ink-subtle">
                          <span className="font-semibold">Key fields:</span> {s.keyFields.join(', ')}
                        </p>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="text-[11px] text-ink-subtle">Read live from Salesforce Setup (Path Settings). The guidance is exactly as entered there.</p>
    </div>
  );
}
