import { Archive, Trash2, Unplug } from 'lucide-react';
import { useEffect, useState } from 'react';
import { errorMessage } from '@/api/client';
import { useOrgPeople, useRemoveOrg, useSavedResults } from '@/api/queries';
import { useToast } from '@/context/ToastContext';
import { cx, fmtNumber } from '@/lib/format';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Overlay';

/** Disconnect an org, choosing whether to keep its saved results or delete them permanently. */
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
  const [mode, setMode] = useState<'keep' | 'delete'>('keep');
  const [sure, setSure] = useState(false);
  useEffect(() => {
    if (open) {
      setMode(deleteOnly ? 'delete' : 'keep');
      setSure(false);
      remove.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const checks = saved.data?.checks ?? 0;
  const problems = saved.data?.problems ?? 0;
  const deleting = mode === 'delete';

  const go = () => {
    if (!orgId) return;
    remove.mutate(
      { orgId, deleteResults: deleting },
      {
        onSuccess: () => {
          notify(
            deleteOnly ? 'Saved results deleted' : deleting ? 'Disconnected and deleted' : 'Salesforce disconnected',
            deleting ? `${orgName}'s access and its ${fmtNumber(checks)} saved health checks were removed.` : 'Access was revoked. Saved results are kept and marked as disconnected.',
            'success',
          );
          onClose();
        },
      },
    );
  };

  const Option = ({ value, icon, title, text }: { value: 'keep' | 'delete'; icon: React.ReactNode; title: string; text: string }) => (
    <button
      type="button"
      onClick={() => {
        setMode(value);
        setSure(false);
      }}
      className={cx(
        'flex w-full items-start gap-3 rounded-xl border-2 p-4 text-left transition',
        mode === value ? (value === 'delete' ? 'border-bad bg-bad-soft/50' : 'border-brand bg-brand-soft/50') : 'border-line hover:border-ink-subtle/40',
      )}
    >
      <span className={cx('mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg', value === 'delete' ? 'bg-bad-soft text-bad' : 'bg-brand-soft text-brand')}>{icon}</span>
      <span>
        <span className="block text-sm font-semibold">{title}</span>
        <span className="mt-0.5 block text-xs text-ink-muted">{text}</span>
      </span>
    </button>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={deleteOnly ? `Delete ${orgName}'s saved results?` : `Disconnect ${orgName} for everyone?`}
      description={deleteOnly ? 'This org is already disconnected. Its saved health checks are still kept.' : 'The platform stops reading this org straight away and its access keys are revoked in Salesforce.'}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" icon={deleting ? <Trash2 className="h-4 w-4" /> : <Unplug className="h-4 w-4" />} disabled={remove.isPending || (deleting && !sure)} onClick={go}>
            {remove.isPending ? 'Working…' : deleteOnly ? 'Delete saved results' : deleting ? 'Disconnect and delete' : 'Disconnect'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {!deleteOnly && !!people.data?.length && (
          <p className="rounded-lg border border-warn/30 bg-warn-soft/60 px-3 py-2 text-sm text-ink">
            This disconnects it for <span className="font-semibold">{people.data.length === 1 ? 'the 1 person' : `all ${people.data.length} people`}</span> who use it:{' '}
            {people.data.join(', ')}. To only take it off your own list, use <span className="font-semibold">Remove from my list</span> instead.
          </p>
        )}
        <p className="text-sm text-ink-muted">
          {saved.isLoading ? 'Counting saved results…' : `Saved for this org: ${fmtNumber(checks)} health check${checks === 1 ? '' : 's'} with ${fmtNumber(problems)} problems (including notes and fix status).`}
        </p>
        {!deleteOnly && (
          <>
            <Option value="keep" icon={<Archive className="h-4 w-4" />} title="Disconnect and keep results" text="Past scores, problems and notes stay, clearly marked as from a disconnected org. Reconnecting the same org carries on from them." />
            <Option value="delete" icon={<Trash2 className="h-4 w-4" />} title="Disconnect and delete results" text="Permanently deletes this org's health checks, problems, notes, schedule and alerts. This can't be undone." />
          </>
        )}
        {deleting && (
          <label className="flex cursor-pointer items-start gap-2 rounded-lg bg-bad-soft px-3 py-2.5 text-sm text-bad">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[rgb(var(--bad))]" />
            <span>I understand this permanently deletes {fmtNumber(checks)} health check{checks === 1 ? '' : 's'} and {fmtNumber(problems)} problems for {orgName}.</span>
          </label>
        )}
        {remove.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(remove.error)}</p>}
      </div>
    </Modal>
  );
}
