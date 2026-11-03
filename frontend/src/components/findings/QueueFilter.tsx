import { useQuery } from '@tanstack/react-query';
import { Users } from 'lucide-react';
import { indicatorApi } from '@/api/endpoints';
import { cx, fmtNumber } from '@/lib/format';

/** Stuck Leads in Queue: every Lead queue in the org, with how many stuck Leads sit in each, as a clickable list beside the
 *  records. Clicking one shows only its Leads; "All queues" shows them all again. */
export function QueueFilter({
  assessmentId,
  areaId,
  label,
  object,
  value,
  onChange,
}: {
  assessmentId: string;
  areaId: string;
  label: string;
  object: string;
  value: string | undefined;
  onChange: (queue: string | undefined) => void;
}) {
  const queues = useQuery({
    queryKey: ['indicator-queues', assessmentId, areaId, label, object],
    queryFn: ({ signal }) => indicatorApi.queues(assessmentId, areaId, label, object, signal),
    staleTime: 60_000,
  });
  const list = queues.data ?? [];
  const total = list.reduce((n, q) => n + q.count, 0);
  const item = (name: string | undefined, text: string, count: number | null) => {
    const on = value === name;
    return (
      <li key={name ?? ''} className="shrink-0">
        <button
          type="button"
          onClick={() => onChange(name)}
          aria-pressed={on}
          className={cx(
            'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition',
            on ? 'bg-brand-soft font-semibold text-brand-ink ring-1 ring-brand/30' : 'text-ink-muted hover:bg-muted hover:text-ink',
          )}
          title={name ? `Show only the Leads in ${name}` : 'Show the Leads in every queue'}
        >
          <span className={cx('min-w-0 flex-1 truncate', count === 0 && !on && 'text-ink-subtle')}>{text}</span>
          {count != null && (
            <span className={cx('rounded-full px-1.5 tabular-nums', count ? (on ? 'bg-surface' : 'bg-bad-soft text-bad') : 'bg-muted text-ink-subtle')}>
              {fmtNumber(count)}
            </span>
          )}
        </button>
      </li>
    );
  };
  return (
    <nav aria-label="Queues" className="rounded-xl border border-line bg-surface p-2 lg:w-56 lg:shrink-0">
      <p className="flex items-center gap-1.5 px-2.5 pb-1.5 pt-0.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        <Users className="h-3.5 w-3.5" /> Lead queues
      </p>
      {queues.isLoading ? (
        <p className="px-2.5 py-2 text-xs text-ink-subtle">Loading queues…</p>
      ) : queues.error ? (
        <p className="px-2.5 py-2 text-xs text-bad">Couldn’t load the queues.</p>
      ) : (
        // A row of chips on narrow screens, a list beside the records on wide ones.
        <ul className="scrollbar-thin flex gap-1 overflow-x-auto lg:max-h-[26rem] lg:flex-col lg:overflow-y-auto lg:overflow-x-visible">
          {item(undefined, 'All queues', total)}
          {list.map((q) => item(q.name, q.name, q.count))}
          {!list.length && <li className="px-2.5 py-1.5 text-xs text-ink-subtle">No Lead queues found.</li>}
        </ul>
      )}
    </nav>
  );
}
