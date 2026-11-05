import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, Calendar, Check, Contact, Hourglass, Mail, Power, Server, UserCheck, Users, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { indicatorApi } from '@/api/endpoints';
import { RecordLink } from '@/components/data/RecordLink';
import { cx, fmtNumber } from '@/lib/format';

const TILE_ICONS: Record<string, ReactNode> = {
  master: <Power className="h-4 w-4" />,
  email: <Mail className="h-4 w-4" />,
  calendar: <Calendar className="h-4 w-4" />,
  contact: <Contact className="h-4 w-4" />,
};

function Heading({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <h4 className="mb-2.5 flex items-center gap-2 text-xs font-medium text-ink-muted">
      {icon}
      {children}
    </h4>
  );
}

function Stat({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="rounded-xl bg-muted/50 px-4 py-3">
      <p className="flex items-center gap-1.5 text-xs text-ink-muted">
        {icon}
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

/** Einstein Activity Capture (EAC) Health: system status, assigned users and the ones needing attention, and the activity
 *  flowing in, read live from Salesforce. Only what Salesforce's APIs expose is shown. */
export function EacHealth({ assessmentId }: { assessmentId: string }) {
  const data = useQuery({
    queryKey: ['eac-health', assessmentId],
    queryFn: ({ signal }) => indicatorApi.eacHealth(assessmentId, signal),
    staleTime: 60_000,
  });
  if (data.isLoading) return <p className="text-sm text-ink-subtle">Reading Einstein Activity Capture from Salesforce…</p>;
  if (data.error)
    return <p className="rounded-lg bg-bad-soft/50 px-4 py-3 text-sm text-bad">Couldn’t read Einstein Activity Capture: {(data.error as Error).message}</p>;
  const d = data.data!;
  const tone = d.status === 'Healthy' ? 'bg-good-soft text-good' : d.status === 'Warning' ? 'bg-warn-soft text-warn' : 'bg-muted text-ink-muted';

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold">Einstein Activity Capture (EAC) Health</p>
        <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium', tone)}>
          {d.status === 'Warning' && <AlertTriangle className="h-3.5 w-3.5" />}
          {d.status}
        </span>
      </div>

      <section>
        <Heading icon={<Server className="h-3.5 w-3.5" />}>A. System status</Heading>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {d.tiles.map((t) => (
            <div key={t.key} className="flex items-center justify-between gap-2 rounded-xl bg-muted/50 px-3 py-2.5" title={t.setting ? `Salesforce setting: ${t.setting}` : 'No EAC setting for this in Salesforce'}>
              <span className="flex items-center gap-2 text-sm">
                {TILE_ICONS[t.key]}
                {t.label}
              </span>
              {t.on == null ? (
                <span className="text-[11px] text-ink-subtle">Not available</span>
              ) : t.on ? (
                <span className="flex items-center gap-1 text-xs font-medium text-good"><Check className="h-3.5 w-3.5" /> On</span>
              ) : (
                <span className="flex items-center gap-1 text-xs font-medium text-bad"><X className="h-3.5 w-3.5" /> Off</span>
              )}
            </div>
          ))}
        </div>
        {!d.settings.available && <p className="mt-2 text-[11px] text-ink-subtle">{d.settings.error}</p>}
        {d.settings.flags.length > 0 && (
          <details className="mt-2 text-xs text-ink-muted">
            <summary className="cursor-pointer select-none">All EAC settings from Salesforce ({d.settings.flags.length})</summary>
            <ul className="mt-1.5 grid gap-1 sm:grid-cols-2">
              {d.settings.flags.map((f) => (
                <li key={f.name} className="flex items-center gap-1.5">
                  {f.on ? <Check className="h-3.5 w-3.5 text-good" /> : <X className="h-3.5 w-3.5 text-bad" />}
                  {f.label}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <section>
        <Heading icon={<Users className="h-3.5 w-3.5" />}>B. User connectivity and health</Heading>
        <div className="grid grid-cols-3 gap-2">
          <Stat icon={<Users className="h-3.5 w-3.5" />} label="Total assigned" value={fmtNumber(d.users.total)} />
          <Stat icon={<UserCheck className="h-3.5 w-3.5" />} label="Active" value={fmtNumber(d.users.active)} />
          <Stat icon={<Hourglass className="h-3.5 w-3.5" />} label="Needs attention" value={fmtNumber(d.users.attention)} />
        </div>
        {d.sources.length > 0 ? (
          <p className="mt-1.5 text-[11px] text-ink-subtle">Assigned by {d.sources.join(' · ')}</p>
        ) : (
          <p className="mt-1.5 text-[11px] text-ink-subtle">No permission set or licence named “Activity Capture” found, so no users are listed.</p>
        )}
        {d.users.issues.length > 0 && (
          <div className="mt-3 overflow-hidden rounded-xl border border-bad/40">
            <p className="flex items-center gap-1.5 bg-bad-soft px-3 py-2 text-xs font-medium text-bad">
              <AlertTriangle className="h-3.5 w-3.5" /> Action required
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-ink-muted">
                  <tr className="border-b border-line">
                    <th className="px-3 py-2 font-medium">User</th>
                    <th className="px-3 py-2 font-medium">Profile</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {d.users.issues.map((u) => (
                    <tr key={u.id}>
                      <td className="px-3 py-2"><RecordLink object="User" id={u.id}>{u.name}</RecordLink></td>
                      <td className="px-3 py-2 text-ink-muted">{u.profile ?? '—'}</td>
                      <td className="px-3 py-2">
                        <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium', u.tone === 'bad' ? 'bg-bad-soft text-bad' : 'bg-warn-soft text-warn')}>
                          {u.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <p className="mt-2 text-[11px] text-ink-subtle">
          Each user’s EAC mailbox connection (expired token, pending authentication) isn’t shown: Salesforce’s APIs don’t expose it. See Setup → Einstein Activity Capture.
        </p>
      </section>

      <section>
        <Heading icon={<Activity className="h-3.5 w-3.5" />}>C. Data pipeline activity</Heading>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {d.pipeline.map((p) => (
            <Stat key={p.key} icon={null} label={p.label} value={p.value == null ? <span className="text-sm font-normal text-ink-subtle">Not available</span> : fmtNumber(p.value)} />
          ))}
        </div>
        <p className="mt-2 text-[11px] text-ink-subtle">The emails EAC captures are stored outside Salesforce, so they can’t be counted here.</p>
      </section>
    </div>
  );
}
