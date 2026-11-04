import { useQuery } from '@tanstack/react-query';
import { Clock, Users, X } from 'lucide-react';
import { indicatorApi } from '@/api/endpoints';
import { InfoTip } from '@/components/ui/HelpTip';
import { cx, fmtNumber } from '@/lib/format';

export type PickedQueue = { id: string; name: string };

/** Stuck Queue-Owned Leads: how long a Lead has waited in its queue to be listed (0 = every Lead in a queue). */
export const QUEUE_DAYS = [3, 5, 7] as const;

export function QueueDays({ value, onChange }: { value: number; onChange: (days: number) => void }) {
  const chip = (days: number, text: string) => (
    <button
      key={days}
      type="button"
      aria-pressed={value === days}
      onClick={() => onChange(days)}
      className={cx(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-xs transition',
        value === days ? 'border-brand bg-brand-soft font-semibold text-brand-ink' : 'border-line hover:border-brand/40 hover:text-brand',
      )}
    >
      {text}
    </button>
  );
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Days in queue">
      <span className="mr-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        <Clock className="h-3.5 w-3.5" /> In a queue
      </span>
      {QUEUE_DAYS.map((d) => chip(d, `More than ${d} days`))}
      {chip(0, 'Any time')}
    </div>
  );
}

/** Every Lead queue in the org side by side above the records (Stuck Queue-Owned Leads, Inactive Lead Assignment Rules), with
 *  how many of the card's Leads sit in each. Clicking one shows only its Leads; "All" (or clicking it again) shows every queue's. */
export function QueueFilter({
  assessmentId,
  areaId,
  label,
  object,
  value,
  days,
  onChange,
  title = 'Lead queues',
  tip,
  empty = 'No Lead queues found.',
}: {
  assessmentId: string;
  areaId: string;
  label: string;
  object: string;
  value: PickedQueue | undefined;
  /** Stuck Queue-Owned Leads: the days-in-queue threshold picked (the counts follow it). */
  days?: number;
  onChange: (queue: PickedQueue | undefined) => void;
  /** The chips' heading, what it means, and what to say when there are none. */
  title?: string;
  tip?: string;
  empty?: string;
}) {
  const queues = useQuery({
    queryKey: ['indicator-queues', assessmentId, areaId, label, object, days],
    queryFn: ({ signal }) => indicatorApi.queues(assessmentId, areaId, label, object, signal, days),
    staleTime: 60_000,
  });
  const list = queues.data ?? [];
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={title}>
      <span className="mr-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        <Users className="h-3.5 w-3.5" /> {title}
        {tip && <InfoTip label={`About ${title}`}>{tip}</InfoTip>}
      </span>
      {queues.isLoading ? (
        <span className="text-xs text-ink-subtle">Loading queues…</span>
      ) : queues.error ? (
        <span className="text-xs text-bad">Couldn’t load the queues.</span>
      ) : !list.length ? (
        <span className="text-xs text-ink-subtle">{empty}</span>
      ) : (
        [
          <button
            key="all"
            type="button"
            aria-pressed={!value}
            onClick={() => onChange(undefined)}
            title="Show every queue’s Leads"
            className={cx(
              'inline-flex items-center rounded-full border px-2.5 py-1 text-xs transition',
              !value ? 'border-brand bg-brand-soft font-semibold text-brand-ink' : 'border-line hover:border-brand/40 hover:text-brand',
            )}
          >
            All
          </button>,
          ...list.map((q) => {
          const on = value?.id === q.id;
          return (
            <button
              key={q.id}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(on ? undefined : { id: q.id, name: q.name })}
              title={on ? 'Show every queue’s Leads' : `Show only the Leads in ${q.name}`}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition',
                on ? 'border-brand bg-brand-soft font-semibold text-brand-ink' : 'border-line hover:border-brand/40 hover:text-brand',
                !on && !q.count && 'text-ink-subtle',
              )}
            >
              {q.name}
              <span className={cx('rounded-full px-1.5 tabular-nums', on ? 'bg-surface' : q.count ? 'bg-bad-soft text-bad' : 'bg-muted')}>{fmtNumber(q.count)}</span>
              {on && <X className="h-3 w-3" aria-hidden="true" />}
            </button>
          );
          }),
        ]
      )}
    </div>
  );
}
