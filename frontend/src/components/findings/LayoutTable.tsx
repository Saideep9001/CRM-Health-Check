import { ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { Select } from '@/components/ui/Form';
import { useExpand } from '@/components/ui/Expand';
import { cx, fmtNumber } from '@/lib/format';
import type { LayoutListItem } from '@/types';

const OBJECTS = ['Account', 'Contact', 'Lead', 'Opportunity'] as const;
const SHOWN_PROFILES = 5;

/** A layout's profiles, easy to read: how many, the busiest ones with their active users, the rest folded away, and the record
 *  types it's used for once (not repeated per profile). */
export function ProfilesCell({ row }: { row: LayoutListItem }) {
  const list = row.profileList;
  if (list == null) {
    // saved by an older health check: the plain list
    return row.profiles == null ? <span className="text-ink-subtle">Couldn’t be read</span> : <span>{row.profiles.join(', ') || '—'}</span>;
  }
  if (!list.length) return <span className="text-ink-subtle">Not assigned to any profile</span>;
  const withUsers = list.filter((p) => p.users > 0);
  const top = withUsers.slice(0, SHOWN_PROFILES);
  const rest = list.filter((p) => !top.includes(p));
  const types = row.recordTypes ?? [];
  return (
    <div className="min-w-[16rem] space-y-1.5 whitespace-normal">
      <p className="text-[11px] text-ink-muted">
        <span className="font-semibold text-ink">{fmtNumber(list.length)}</span> profile{list.length === 1 ? '' : 's'}
        {' · '}
        <span className="font-semibold text-ink">{fmtNumber(withUsers.length)}</span> with active users
      </p>
      {top.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {top.map((p) => (
            <li key={p.name} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2 py-0.5 text-[11px] text-ink"
              title={p.recordTypes.length ? `Record types: ${p.recordTypes.join(', ')}` : undefined}>
              {p.name} <span className="tabular-nums text-ink-subtle">{fmtNumber(p.users)}</span>
            </li>
          ))}
        </ul>
      )}
      {rest.length > 0 && (
        <details className="group text-[11px]">
          <summary className="cursor-pointer select-none font-medium text-brand hover:underline">
            {top.length ? `+ ${fmtNumber(rest.length)} more profile${rest.length === 1 ? '' : 's'}` : `Show ${fmtNumber(rest.length)} profile${rest.length === 1 ? '' : 's'}`}
            {rest.every((p) => p.users === 0) && ' (no active users)'}
          </summary>
          <ul className="mt-1 max-h-48 space-y-0.5 overflow-auto rounded-md border border-line bg-muted/40 p-2">
            {rest.map((p) => (
              <li key={p.name} className={cx('flex justify-between gap-3', p.users === 0 && 'text-ink-subtle')}>
                <span className="truncate" title={p.name}>{p.name}</span>
                <span className="shrink-0 tabular-nums">{p.users ? `${fmtNumber(p.users)} user${p.users === 1 ? '' : 's'}` : 'no users'}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {types.length > 0 && (
        <p className="text-[11px] text-ink-muted" title={types.join(', ')}>
          <span className="font-medium text-ink">Record types:</span> {types.slice(0, 4).join(', ')}
          {types.length > 4 && ` +${types.length - 4} more`}
        </p>
      )}
    </div>
  );
}

/** Layout usability concerns: every page layout with its fields, the profiles it's assigned to, and how many users get it. */
export function LayoutTable({ rows }: { rows: LayoutListItem[] }) {
  const ex = useExpand();
  const [object, setObject] = useState('');
  const shown = rows.filter((r) => !object || r.object === object);
  const inactive = shown.filter((r) => r.active === false).length;

  return ex.wrap(
    <section className={cx('overflow-hidden rounded-xl border border-line', ex.boxClass)}>
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-muted/50 px-3 py-2">
        <span className="text-sm font-semibold">Page layouts</span>
        <span className="rounded-full bg-surface px-2 text-[11px] tabular-nums text-ink-muted">{fmtNumber(shown.length)}</span>
        {inactive > 0 && <span className="rounded-full bg-muted px-2 text-[11px] font-medium text-ink-muted">{fmtNumber(inactive)} inactive</span>}
        <div className="ml-auto flex items-center gap-2 [&_select]:h-7 [&_select]:py-0 [&_select]:text-xs">
          <Select<string> label="Object" className="w-36" value={object} onChange={setObject}
            options={[{ value: '', label: 'All objects' }, ...OBJECTS.map((o) => ({ value: o, label: o }))]} />
          {ex.button}
        </div>
      </header>
      {shown.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-ink-subtle">No page layouts to show here.</p>
      ) : (
        <div className={ex.scrollClass('max-h-[28rem]')}>
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
              <tr className="text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
                <th className="px-3 py-2">Object</th>
                <th className="px-3 py-2">Layout Name</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Total Fields</th>
                <th className="px-3 py-2 text-right">Required Fields</th>
                <th className="px-3 py-2">Assigned Profiles</th>
                <th className="px-3 py-2 text-right">Usage Percentage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {shown.map((r, i) => (
                <tr key={`${r.object}-${r.name}-${i}`} className="align-top hover:bg-muted/60">
                  <td className="px-3 py-2">{r.object}</td>
                  <td className="max-w-[16rem] px-3 py-2">
                    {r.url ? (
                      <a href={r.url} target="_blank" rel="noopener noreferrer" title="Open this layout in Salesforce Setup"
                        className="inline-flex items-center gap-1 font-medium text-ink hover:text-brand hover:underline">
                        <span className="break-words">{r.name}</span> <ExternalLink className="h-3 w-3 shrink-0 text-ink-subtle" />
                      </a>
                    ) : (
                      <span className="font-medium">{r.name}</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {r.active == null ? (
                      <span className="text-ink-subtle" title="The layout assignments couldn’t be read">Unknown</span>
                    ) : (
                      <span className={cx('rounded-full px-2 py-0.5 text-[11px] font-medium', r.active ? 'bg-good-soft text-good' : 'bg-muted text-ink-muted')}
                        title={r.active ? 'Assigned to a profile with active users' : 'Not assigned to any profile with active users'}>
                        {r.active ? 'Active' : 'Inactive'}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmtNumber(r.fields)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.required == null ? <span className="text-ink-subtle">N/A</span> : fmtNumber(r.required)}</td>
                  <td className="max-w-[26rem] px-3 py-2"><ProfilesCell row={r} /></td>
                  <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums" title={r.users != null ? `${fmtNumber(r.users)} active user(s)` : undefined}>
                    {r.usage == null ? <span className="text-ink-subtle">N/A</span> : `${r.usage}%`}
                    {r.users != null && <span className="block text-[11px] text-ink-subtle">{fmtNumber(r.users)} user{r.users === 1 ? '' : 's'}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="border-t border-line bg-muted/30 px-3 py-1.5 text-[11px] text-ink-muted">
        Active: assigned to a profile with active users. Record types a profile gets the layout for are in brackets. Usage: the share of active users
        (in the profiles with this object’s layouts) who get the layout; with record types a user can get several, so totals can pass 100%.
      </p>
    </section>,
  );
}
