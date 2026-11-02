import { Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { errorMessage } from '@/api/client';
import { useOrgPeople, useRemoveOrg, useSavedResults } from '@/api/queries';
import { useToast } from '@/context/ToastContext';
import { fmtNumber } from '@/lib/format';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Overlay';

/** Disconnect an org. Nothing about it outlives the connection: its health checks, problems, notes, schedule and alerts are deleted too. */
export function DisconnectDialog({
  open,
  orgId,
  orgName,
  onClose,
  deleteOnly,
}: {
  open: boolean;
  orgId: string | null;
  orgName: string;
  onClose: () => void;
  /** The org is already disconnected: only offer deleting its saved results. */
  deleteOnly?: boolean;
}) {
  const saved = useSavedResults(orgId, open);
  const people = useOrgPeople(orgId, open && !deleteOnly);
  const remove = useRemoveOrg();
  const { notify } = useToast();
  const [sure, setSure] = useState(false);
  useEffect(() => {
    if (open) {
      setSure(false);
      remove.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const checks = saved.data?.checks ?? 0;
  const problems = saved.data?.problems ?? 0;

  const go = () => {
    if (!orgId) return;
    remove.mutate(
      { orgId, deleteResults: true },
      {
        onSuccess: () => {
          notify(
            deleteOnly ? 'Saved results deleted' : 'Disconnected and deleted',
            `${orgName}'s access and its ${fmtNumber(checks)} health checks were removed. Nothing about it is kept.`,
            'success',
          );
          onClose();
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={deleteOnly ? `Delete ${orgName}'s saved results?` : `Disconnect ${orgName} for everyone?`}
      description={deleteOnly ? 'This org is already disconnected. Its leftover health checks can be deleted.' : 'The platform stops reading this org straight away, its access keys are revoked in Salesforce, and everything saved about it is deleted.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} disabled={remove.isPending || !sure} onClick={go}>
            {remove.isPending ? 'Working…' : deleteOnly ? 'Delete saved results' : 'Disconnect and delete'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {!deleteOnly && !!people.data?.length && (
          <p className="rounded-lg border border-warn/30 bg-warn-soft/60 px-3 py-2 text-sm text-ink">
            This disconnects it for <span className="font-semibold">{people.data.length === 1 ? 'the 1 person' : `all ${people.data.length} people`}</span> who {people.data.length === 1 ? 'uses' : 'use'} it:{' '}
            {people.data.join(', ')}. To only take it off your own list, use <span className="font-semibold">Remove from my list</span> instead.
          </p>
        )}
        <p className="text-sm text-ink-muted">
          {saved.isLoading ? 'Counting saved results…' : `Results are only kept while an org is connected. Saved for this org now: ${fmtNumber(checks)} health check${checks === 1 ? '' : 's'} with ${fmtNumber(problems)} problems.`}
        </p>
        <label className="flex cursor-pointer items-start gap-2 rounded-lg bg-bad-soft px-3 py-2.5 text-sm text-bad">
          <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[rgb(var(--bad))]" />
          <span>
            I understand this permanently deletes {fmtNumber(checks)} health check{checks === 1 ? '' : 's'} and {fmtNumber(problems)} problems (with their notes, schedule
            and alerts) for {orgName}{deleteOnly ? '' : ', for everyone who uses it'}. Reconnecting later starts fresh.
          </span>
        </label>
        {remove.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(remove.error)}</p>}
      </div>
    </Modal>
  );
}
