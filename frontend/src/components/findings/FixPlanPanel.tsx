import { ListChecks, Loader2, ShieldAlert } from 'lucide-react';
import { useEffect } from 'react';
import { errorMessage } from '@/api/client';
import { useFixPlan } from '@/api/queries';
import { Button } from '../ui/Button';

/** Step-by-step plan for fixing a problem, from the built-in playbooks. */
export function FixPlanPanel({ findingId }: { findingId: string }) {
  const plan = useFixPlan();
  useEffect(() => plan.reset(), [findingId]); // eslint-disable-line react-hooks/exhaustive-deps
  const p = plan.data;

  if (!p) {
    return (
      <div className="mt-3">
        <Button size="sm" icon={plan.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ListChecks className="h-3.5 w-3.5" />} onClick={() => plan.mutate(findingId)} disabled={plan.isPending}>
          {plan.isPending ? 'Writing the plan…' : 'Get a step-by-step fix plan'}
        </Button>
        {plan.error && <p className="mt-2 text-xs text-bad">{errorMessage(plan.error)}</p>}
      </div>
    );
  }
  return (
    <div className="mt-3 rounded-xl border border-line p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold">Fix plan</p>
        {p.effortHours ? <span className="ml-auto text-xs text-ink-subtle">About {p.effortHours} hours</span> : null}
      </div>
      <ol className="space-y-2">
        {p.steps.map((s, i) => (
          <li key={i} className="flex gap-3 text-sm">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand text-[11px] font-semibold text-white">{i + 1}</span>
            <span>
              <span className="font-medium">{s.title}</span>
              <span className="block text-ink-muted">{s.detail}</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-3 flex gap-2 rounded-lg bg-warn-soft px-3 py-2 text-xs text-ink"><ShieldAlert className="h-4 w-4 shrink-0 text-warn" />{p.risks}</p>
    </div>
  );
}
