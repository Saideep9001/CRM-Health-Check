import { AlertTriangle, ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { Select } from '@/components/ui/Form';
import { useExpand } from '@/components/ui/Expand';
import { cx, fmtNumber } from '@/lib/format';
import type { RuleAuditItem } from '@/types';

const OBJECTS = ['Account', 'Contact', 'Lead', 'Opportunity'] as const;
const AREAS = ['Page Layout', 'Validation Rule', 'Trigger', 'System Rule'] as const;
type Status = 'all' | 'active' | 'inactive';

/** Which rules a status shows:
 *  Active — validation rules and triggers whose error message is unclear (empty, only “Error” / “Invalid”, generic or too short);
 *           page layout and system rules (their message is Salesforce's own, so N/A).
 *  Inactive — every inactive rule, whatever its message.
 *  All — both. */
function shows(r: RuleAuditItem, status: Status): boolean {
  const activeView = r.active && (!r.assessed || !!r.issue);
  if (status === 'active') return activeView;
  if (status === 'inactive') return !r.active;
  return activeView || !r.active;
}

/** The validation rules card: every rule that stops a save, by object, status and kind, with its error message judged. */
export function RuleAuditTable({ rows }: { rows: RuleAuditItem[] }) {
  const ex = useExpand();
  const [object, setObject] = useState('');
  const [status, setStatus] = useState<Status>('all');
  const [area, setArea] = useState('');
  const shown = rows.filter((r) => (!object || r.object === object) && (!area || r.area === area) && shows(r, status));
  const unclear = shown.filter((r) => r.active && r.issue).length;

  return ex.wrap(
    <section className={cx('overflow-hidden rounded-xl border border-line', ex.boxClass)}>
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-muted/50 px-3 py-2">
        <span className="text-sm font-semibold">Rules</span>
        <span className="rounded-full bg-surface px-2 text-[11px] tabular-nums text-ink-muted">{fmtNumber(shown.length)}</span>
        {unclear > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-bad-soft px-2 text-[11px] font-medium text-bad">
            <AlertTriangle className="h-3 w-3" /> {fmtNumber(unclear)} unclear message{unclear === 1 ? '' : 's'}
          </span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2 [&_select]:h-7 [&_select]:py-0 [&_select]:text-xs">
          <Select<string> label="Object" className="w-36" value={object} onChange={setObject}
            options={[{ value: '', label: 'All objects' }, ...OBJECTS.map((o) => ({ value: o, label: o }))]} />
          <Select<Status> label="Status" className="w-32" value={status} onChange={setStatus}
            options={[{ value: 'all', label: 'All statuses' }, { value: 'active', label: 'Active' }, { value: 'inactive', label: 'Inactive' }]} />
          <Select<string> label="Area" className="w-40" value={area} onChange={setArea}
            options={[{ value: '', label: 'All areas' }, ...AREAS.map((a) => ({ value: a, label: a }))]} />
          {ex.button}
        </div>
      </header>
      {shown.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-ink-subtle">
          {status === 'active' ? 'No active rules with an unclear error message here.' : status === 'inactive' ? 'No inactive rules here.' : 'No rules to show here.'}
        </p>
      ) : (
        <div className={ex.scrollClass('max-h-[28rem]')}>
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
              <tr className="text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                <th className="px-3 py-2">Rule Name</th>
                <th className="px-3 py-2">Description</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Error Message</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {shown.map((r, i) => (
                <tr key={`${r.object}-${r.area}-${r.name}-${i}`} className="align-top hover:bg-muted/60">
                  <td className="max-w-[16rem] px-3 py-2">
                    {r.url ? (
                      <a href={r.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-ink hover:text-brand hover:underline"
                        title="Open this rule in Salesforce Setup">
                        <span className="break-all">{r.name}</span> <ExternalLink className="h-3 w-3 shrink-0 text-ink-subtle" />
                      </a>
                    ) : (
                      <span className="break-all font-medium">{r.name}</span>
                    )}
                    <span className="mt-0.5 block text-[11px] text-ink-muted">{r.object} · {r.area}</span>
                  </td>
                  <td className="max-w-[22rem] whitespace-normal break-words px-3 py-2 text-ink-muted">{r.description || '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <span className={cx('rounded-full px-2 py-0.5 text-[11px] font-medium', r.active ? 'bg-good-soft text-good' : 'bg-muted text-ink-muted')}>
                      {r.active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className={cx('max-w-[20rem] whitespace-normal break-words px-3 py-2', r.active && r.issue && 'bg-bad-soft/60')}>
                    {!r.assessed ? (
                      <span className="text-ink-subtle" title="Salesforce shows its own standard message for this rule, or the message isn’t written in the code">N/A</span>
                    ) : r.message ? (
                      r.message
                    ) : (
                      <span className="text-ink-subtle">{r.active ? '(empty)' : 'N/A'}</span>
                    )}
                    {r.active && r.issue && (
                      <span className="mt-0.5 flex items-start gap-1 text-[10.5px] font-medium leading-snug text-bad">
                        <AlertTriangle className="mt-px h-3 w-3 shrink-0" /> {r.issue}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="border-t border-line bg-muted/30 px-3 py-1.5 text-[11px] text-ink-muted">
        Active shows validation rules and triggers with an unclear error message, plus page layout and system rules (Salesforce’s own message: N/A).
        Inactive shows every inactive rule. All shows both.
      </p>
    </section>,
  );
}
