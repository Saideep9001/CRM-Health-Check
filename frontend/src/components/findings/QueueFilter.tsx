import { useQuery } from '@tanstack/react-query';
import { indicatorApi } from '@/api/endpoints';
import { fmtNumber } from '@/lib/format';

/** Stuck Leads in Queue: show only the Leads in one queue (the queues they sit in, with how many in each). */
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
  return (
    <select
      className="input h-7 w-auto max-w-[14rem] py-0 text-xs"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value || undefined)}
      disabled={queues.isLoading || (!list.length && !value)}
      aria-label="Queue"
      title="Show only the Leads in one queue"
    >
      <option value="">{queues.isLoading ? 'Loading queues…' : `All queues${list.length ? ` (${fmtNumber(total)})` : ''}`}</option>
      {list.map((q) => (
        <option key={q.name} value={q.name}>
          {q.name} ({fmtNumber(q.count)})
        </option>
      ))}
    </select>
  );
}
