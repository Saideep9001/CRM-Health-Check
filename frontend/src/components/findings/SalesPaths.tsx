import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Route } from 'lucide-react';
import { indicatorApi, type SalesPathData } from '@/api/endpoints';
import { LocalTable } from '@/components/data/LocalTable';
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

/** Sales stage guidance gaps: every Opportunity Sales Process (green = it has an active Sales Path, red = it hasn't). Picking
 *  one shows each of its stages with the Path's "Guidance for Success" and key fields, read live from Salesforce Setup. */
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
        No Opportunity Sales Processes or Sales Paths found in Setup.
      </p>
    );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Sales Processes">
        <span className="mr-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
          <Route className="h-3.5 w-3.5" /> Sales Processes
          <InfoTip label="About Sales Processes">
            Every Opportunity Sales Process in Setup. Green: the Sales Process is active. Red: it’s inactive. A tag shows when it has no Sales Path, or its Path is inactive. Pick one to see each of its stages with the guidance reps see.
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
              title={`Sales Process ${p.processActive ? 'active' : 'inactive'} · ${p.pathName ? `Sales Path: ${p.pathName} (${p.pathActive ? 'active' : 'inactive'})` : 'No Sales Path'} · ${p.guided} of ${p.openStages} open stages have guidance`}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition',
                p.processActive ? 'border-good/40 bg-good-soft text-good' : 'border-bad/40 bg-bad-soft text-bad',
                on ? 'font-semibold ring-2 ring-brand ring-offset-1' : 'hover:brightness-95',
              )}
            >
              <span className={cx('h-1.5 w-1.5 rounded-full', p.processActive ? 'bg-good' : 'bg-bad')} aria-hidden="true" />
              {p.name}
              {!p.pathActive && (
                // the Sales Process is fine, but reps see no guidance: no Path for it, or its Path is turned off
                <span className="rounded-full bg-surface/80 px-1.5 text-[10px] font-medium text-ink-muted">{p.pathName ? 'Path inactive' : 'No Path'}</span>
              )}
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
            <span className={cx('rounded-full px-2 py-0.5 font-medium', path.processActive ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
              {path.processActive ? 'Active' : 'Inactive'}
            </span>
            <span>
              Sales Path:{' '}
              {path.pathName ? (
                <>
                  <span className="font-medium text-ink">{path.pathName}</span>{' '}
                  <span className={cx('rounded-full px-2 py-0.5 font-medium', path.pathActive ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
                    {path.pathActive ? 'Active' : 'Inactive'}
                  </span>
                </>
              ) : (
                <span className="rounded-full bg-bad-soft px-2 py-0.5 font-medium text-bad">None</span>
              )}
            </span>
            {path.recordType && <span>Record Types: <span className="font-medium text-ink">{path.recordType}</span></span>}
            <span>{path.guided} of {path.openStages} open stages have guidance</span>
          </div>
          <div className="p-3">
            <LocalTable
              title="Stages"
              rows={path.stages}
              rowKey={(s) => s.apiName}
              maxHeight="max-h-[36rem]"
              columns={[
                {
                  key: 'stage',
                  label: 'Opportunity Stage',
                  value: (s) => s.stage,
                  className: 'w-52 font-medium',
                  render: (s) => (
                    <>
                      {s.stage}
                      {s.closed && <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-normal text-ink-subtle">Closed</span>}
                    </>
                  ),
                },
                {
                  key: 'guidance',
                  label: 'Guidance',
                  value: (s) => (s.available ? 'Available' : 'Not available'),
                  className: 'w-36',
                  render: (s) => (
                    <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium', s.available ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
                      {s.available ? 'Available' : 'Not available'}
                    </span>
                  ),
                },
                {
                  key: 'details',
                  label: 'Details',
                  filter: false,
                  value: (s) => s.details.join(' '),
                  className: 'text-ink-muted',
                  render: (s) => (
                    <>
                      {s.details.length ? (
                        <Guidance lines={s.details} />
                      ) : (
                        <span className="text-ink-subtle">{path.pathName ? 'No guidance for this stage on the Path.' : 'No Sales Path for this Sales Process.'}</span>
                      )}
                      {s.keyFields.length > 0 && (
                        <p className="mt-1.5 text-[11px] text-ink-subtle">
                          <span className="font-semibold">Key fields:</span> {s.keyFields.join(', ')}
                        </p>
                      )}
                    </>
                  ),
                },
              ]}
            />
          </div>
        </div>
      )}
      <p className="text-[11px] text-ink-subtle">Read live from Salesforce Setup (Sales Processes and Path Settings). The guidance is exactly as entered there.</p>
    </div>
  );
}
