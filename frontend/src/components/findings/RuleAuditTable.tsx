import { AlertTriangle, CheckCircle2, ExternalLink } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Select } from '@/components/ui/Form';
import { useExpand } from '@/components/ui/Expand';
import { cx, fmtNumber } from '@/lib/format';
import type { LayoutListItem, RuleAuditItem } from '@/types';

const OBJECTS = ['Account', 'Contact', 'Lead', 'Opportunity'] as const;
type Area = 'validation' | 'system' | 'trigger' | 'layout';
type Status = 'all' | 'active' | 'inactive';
type Row = RuleAuditItem | LayoutListItem;
type Col = { label: string; cell: (r: Row) => ReactNode; className?: string; flag?: (r: Row) => boolean };

const na = <span className="text-ink-subtle">N/A</span>;
const statusPill = (active: boolean | null) =>
  active == null ? (
    <span className="text-ink-subtle" title="The layout assignments couldn’t be read">Unknown</span>
  ) : (
    <span className={cx('rounded-full px-2 py-0.5 text-[11px] font-medium', active ? 'bg-good-soft text-good' : 'bg-muted text-ink-muted')}>
      {active ? 'Active' : 'Inactive'}
    </span>
  );
const linked = (name: string, url: string | null) =>
  url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" title="Open in Salesforce Setup"
      className="inline-flex items-center gap-1 font-medium text-ink hover:text-brand hover:underline">
      <span className="break-all">{name}</span> <ExternalLink className="h-3 w-3 shrink-0 text-ink-subtle" />
    </a>
  ) : (
    <span className="break-all font-medium">{name}</span>
  );
// a validation rule's or trigger's own message, as written (empty shows as such); none written = N/A
const message = (r: RuleAuditItem) => (!r.assessed ? na : r.message ? r.message : <span className="text-ink-subtle">(empty)</span>);
// an active validation rule's improper message: red, with why
const unclear = (r: Row) => 'assessed' in r && r.active && !!r.issue;
const judged = (r: RuleAuditItem) => (
  <>
    {message(r)}
    {r.active && r.issue && (
      <span className="mt-0.5 flex items-start gap-1 text-[10.5px] font-medium leading-snug text-bad">
        <AlertTriangle className="mt-px h-3 w-3 shrink-0" /> {r.issue}
      </span>
    )}
  </>
);
// an active trigger's message, judged; inactive ones, or messages not written in the code, aren't
const quality = (r: RuleAuditItem) =>
  !r.active || !r.assessed ? na : r.issue ? (
    <span className="flex items-start gap-1 font-medium text-bad"><AlertTriangle className="mt-px h-3 w-3 shrink-0" /> {r.issue}</span>
  ) : (
    <span className="inline-flex items-center gap-1 font-medium text-good"><CheckCircle2 className="h-3 w-3" /> Clear</span>
  );

const rule = (r: Row) => r as RuleAuditItem;
const lay = (r: Row) => r as LayoutListItem;
const wide = 'max-w-[22rem] whitespace-normal break-words';
const AREAS: { key: Area; label: string; status: boolean; empty: string; cols: Col[] }[] = [
  {
    key: 'validation', label: 'Validation Rules', status: true,
    empty: 'No validation rules found on these objects. If you expect some, check “Couldn’t read” in the rules above: the connected user may need “View Setup and Configuration”.',
    cols: [
      { label: 'Object', cell: (r) => r.object },
      { label: 'Rule Name', cell: (r) => linked(r.name, r.url) },
      { label: 'Description', cell: (r) => rule(r).description || '—', className: cx(wide, 'text-ink-muted') },
      { label: 'Status', cell: (r) => statusPill(rule(r).active) },
      { label: 'Error Message', cell: (r) => judged(rule(r)), className: wide, flag: unclear },
    ],
  },
  {
    key: 'system', label: 'System Rules', status: false, empty: 'No system required fields here.',
    cols: [
      { label: 'Object', cell: (r) => r.object },
      { label: 'Field Name', cell: (r) => linked(r.name, r.url) },
      { label: 'Field Label', cell: (r) => rule(r).label ?? '—' },
      { label: 'Data Type', cell: (r) => rule(r).type || '—' },
      { label: 'Required Status', cell: (r) => rule(r).required ?? 'Required' },
      { label: 'Description', cell: (r) => rule(r).description || '—', className: cx(wide, 'text-ink-muted') },
    ],
  },
  {
    key: 'trigger', label: 'Apex Triggers', status: true, empty: 'No Apex triggers that stop a save here.',
    cols: [
      { label: 'Object', cell: (r) => r.object },
      { label: 'Trigger Name', cell: (r) => linked(r.name, r.url) },
      { label: 'Description', cell: (r) => rule(r).description || '—', className: cx(wide, 'text-ink-muted') },
      { label: 'Trigger Event', cell: (r) => rule(r).events || '—' },
      { label: 'Status', cell: (r) => statusPill(rule(r).active) },
      { label: 'Error Message', cell: (r) => message(rule(r)), className: wide, flag: unclear },
      { label: 'Error Message Quality', cell: (r) => quality(rule(r)), className: 'max-w-[14rem] whitespace-normal' },
    ],
  },
  {
    key: 'layout', label: 'Page Layouts', status: false, empty: 'No page layouts here.',
    cols: [
      { label: 'Object', cell: (r) => r.object },
      { label: 'Layout Name', cell: (r) => linked(r.name, r.url) },
      { label: 'Total Fields', cell: (r) => fmtNumber(lay(r).fields), className: 'text-right tabular-nums' },
      { label: 'Required Fields', cell: (r) => (lay(r).required == null ? na : fmtNumber(lay(r).required!)), className: 'text-right tabular-nums' },
      { label: 'Assigned Profiles', cell: (r) => (lay(r).profiles == null ? na : lay(r).profiles!.length ? lay(r).profiles!.join(', ') : '—'), className: cx(wide, 'text-ink-muted') },
      {
        label: 'Usage Percentage', className: 'whitespace-nowrap text-right tabular-nums',
        cell: (r) => (lay(r).usage == null ? na : (
          <>
            {lay(r).usage}%
            {lay(r).users != null && <span className="block text-[11px] text-ink-subtle">{fmtNumber(lay(r).users!)} user{lay(r).users === 1 ? '' : 's'}</span>}
          </>
        )),
      },
    ],
  },
];
const AREA_OF: Record<string, Area> = { 'Validation Rule': 'validation', 'System Rule': 'system', Trigger: 'trigger' };

/** The validation rules card: four tables, one per kind of rule that stops a save, by object (and status where it applies). */
export function RuleAuditTable({ rows, layouts = [] }: { rows: RuleAuditItem[]; layouts?: LayoutListItem[] }) {
  const ex = useExpand();
  const [area, setArea] = useState<Area>('validation');
  const [object, setObject] = useState('');
  const [status, setStatus] = useState<Status>('all');
  const def = AREAS.find((a) => a.key === area)!;
  const of = (a: Area): Row[] => (a === 'layout' ? layouts : rows.filter((r) => AREA_OF[r.area] === a));
  const shown = of(area).filter(
    (r) => (!object || r.object === object) && (!def.status || status === 'all' || (status === 'active') === (r as RuleAuditItem).active),
  );

  return ex.wrap(
    <section className={cx('overflow-hidden rounded-xl border border-line', ex.boxClass)}>
      <div className="flex flex-wrap gap-1.5 border-b border-line px-3 pt-2.5 pb-2">
        {AREAS.map((a) => (
          <button key={a.key} type="button" onClick={() => setArea(a.key)}
            className={cx('rounded-full border px-3 py-1 text-xs font-medium transition',
              a.key === area ? 'border-brand bg-brand-soft text-brand-ink' : 'border-line text-ink-muted hover:text-ink')}>
            {a.label} <span className="ml-1 tabular-nums opacity-70">{fmtNumber(of(a.key).filter((r) => !object || r.object === object).length)}</span>
          </button>
        ))}
      </div>
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-muted/50 px-3 py-2">
        <span className="text-sm font-semibold">{def.label}</span>
        <span className="rounded-full bg-surface px-2 text-[11px] tabular-nums text-ink-muted">{fmtNumber(shown.length)}</span>
        {shown.filter(unclear).length > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-bad-soft px-2 text-[11px] font-medium text-bad">
            <AlertTriangle className="h-3 w-3" /> {fmtNumber(shown.filter(unclear).length)} without a proper error message
          </span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2 [&_select]:h-7 [&_select]:py-0 [&_select]:text-xs">
          <Select<string> label="Object" className="w-36" value={object} onChange={setObject}
            options={[{ value: '', label: 'All objects' }, ...OBJECTS.map((o) => ({ value: o, label: o }))]} />
          {def.status && (
            <Select<Status> label="Status" className="w-32" value={status} onChange={setStatus}
              options={[{ value: 'all', label: 'All statuses' }, { value: 'active', label: 'Active' }, { value: 'inactive', label: 'Inactive' }]} />
          )}
          {ex.button}
        </div>
      </header>
      {shown.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-ink-subtle">{def.empty}</p>
      ) : (
        <div className={ex.scrollClass('max-h-[28rem]')}>
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
              <tr className="text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                {def.cols.map((c) => (
                  <th key={c.label} className={cx('whitespace-nowrap px-3 py-2', c.className?.includes('text-right') && 'text-right')}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {shown.map((r, i) => (
                <tr key={`${r.object}-${r.name}-${i}`} className="align-top hover:bg-muted/60">
                  {def.cols.map((c) => (
                    <td key={c.label} className={cx('px-3 py-2', c.className, c.flag?.(r) && 'bg-bad-soft/60')}>{c.cell(r)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="border-t border-line bg-muted/30 px-3 py-1.5 text-[11px] text-ink-muted">
        {area === 'validation' && 'Every validation rule, active and inactive, with its own error message. Red: an active rule whose message is empty, only “Error” or “Invalid”, generic, or too short to explain the issue.'}
        {area === 'system' && 'Fields Salesforce requires on every record (standard required fields, and custom fields marked Required). Salesforce shows its own message for these.'}
        {area === 'trigger' && 'Triggers that stop a save (addError), active and inactive. Message quality is judged for active triggers whose message is written in their code; otherwise N/A.'}
        {area === 'layout' && 'Every page layout. Usage: the share of active users (in the profiles with this object’s layouts) who get the layout; with record types totals can pass 100%.'}
      </p>
    </section>,
  );
}
