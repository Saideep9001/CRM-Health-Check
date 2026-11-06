import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, Calendar, Check, Contact, Hourglass, Mail, Power, Server, UserCheck, Users, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { indicatorApi, type EacUser } from '@/api/endpoints';
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

/** A row of filter chips: "All", then each value with how many users have it. Clicking a picked chip again clears it. */
export function FilterChips({ title, options, value, onChange }: {
  title: string;
  options: { key: string; label: string; count: number; tone?: 'good' | 'bad' }[];
  value: string | undefined;
  onChange: (v: string | undefined) => void;
}) {
  const toned = { good: 'border-good/40 bg-good-soft text-good', bad: 'border-bad/40 bg-bad-soft text-bad' };
  const chip = (on: boolean) =>
    cx('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition',
      on ? 'border-brand bg-brand-soft font-semibold text-brand-ink' : 'border-line hover:border-brand/40 hover:text-brand');
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={title}>
      <span className="mr-1 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">{title}</span>
      <button type="button" aria-pressed={!value} onClick={() => onChange(undefined)} className={chip(!value)}>All</button>
      {options.map((o) => (
        <button key={o.key} type="button" aria-pressed={value === o.key} onClick={() => onChange(value === o.key ? undefined : o.key)}
          className={cx(chip(value === o.key), o.tone && toned[o.tone], o.tone && value === o.key && 'ring-2 ring-brand ring-offset-1',
            !o.count && value !== o.key && !o.tone && 'text-ink-subtle')}>
          {o.label}
          <span className={cx('rounded-full px-1.5 tabular-nums', value === o.key ? 'bg-surface' : 'bg-muted')}>{fmtNumber(o.count)}</span>
        </button>
      ))}
    </div>
  );
}

const NO_PROFILE = '(no profile)';

/** Einstein Activity Capture (EAC) Health: system status, assigned users and the ones needing attention, and the activity
 *  flowing in, read live from Salesforce. Only what Salesforce's APIs expose is shown. */
export function EacHealth({ assessmentId }: { assessmentId: string }) {
  // the users table: the ones needing attention (default), or everyone assigned EAC
  const [showAll, setShowAll] = useState(false);
  // filters on the users table, from the users' own Salesforce values: their Profile, and Active or not
  const [profile, setProfile] = useState<string | undefined>();
  const [userStatus, setUserStatus] = useState<string | undefined>();
  const data = useQuery({
    queryKey: ['eac-health', assessmentId],
    queryFn: ({ signal }) => indicatorApi.eacHealth(assessmentId, signal),
    staleTime: 60_000,
  });
  if (data.isLoading) return <p className="text-sm text-ink-subtle">Reading Einstein Activity Capture from Salesforce…</p>;
  if (data.error)
    return <p className="rounded-lg bg-bad-soft/50 px-4 py-3 text-sm text-bad">Couldn’t read Einstein Activity Capture: {(data.error as Error).message}</p>;
  const d = data.data!;
  const base: EacUser[] = showAll ? d.users.all ?? [] : d.users.issues;
  const profileOf = (u: EacUser) => u.profile ?? NO_PROFILE;
  const statusOf = (u: EacUser) => (u.isActive === false ? 'inactive' : 'active');
  const byStatus = base.filter((u) => !userStatus || statusOf(u) === userStatus);
  const byProfile = base.filter((u) => !profile || profileOf(u) === profile);
  const shown = byStatus.filter((u) => !profile || profileOf(u) === profile);
  // the picked profile stays listed (with 0) when switching to a view without it, so it can be cleared
  const profiles = [...new Set([...base.map(profileOf), ...(profile ? [profile] : [])])].sort((a, b) => a.localeCompare(b));
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
        {(d.users.issues.length > 0 || (d.users.all?.length ?? 0) > 0) && (
          <div className={cx('mt-3 overflow-hidden rounded-xl border', showAll ? 'border-line' : 'border-bad/40')}>
            <div className={cx('flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs font-medium', showAll ? 'bg-muted/50 text-ink' : 'bg-bad-soft text-bad')}>
              <span className="flex items-center gap-1.5">
                {showAll ? <Users className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
                {showAll ? 'All assigned users' : 'Action required'}
              </span>
              {d.users.all && (
                <span className="inline-flex overflow-hidden rounded-full border border-line bg-surface text-ink-muted" role="group" aria-label="Users shown">
                  {[
                    [false, `Action required (${d.users.issues.length})`],
                    [true, `All users (${d.users.all.length})`],
                  ].map(([all, text]) => (
                    <button
                      key={String(all)}
                      type="button"
                      aria-pressed={showAll === all}
                      onClick={() => setShowAll(all as boolean)}
                      className={cx('px-2.5 py-0.5 transition', showAll === all ? 'bg-brand-soft font-semibold text-brand-ink' : 'hover:text-brand')}
                    >
                      {text as string}
                    </button>
                  ))}
                </span>
              )}
            </div>
            {base.length > 0 && (
              <div className="space-y-1.5 border-b border-line px-3 py-2">
                <FilterChips title="User Profile" value={profile} onChange={setProfile}
                  options={profiles.map((p) => ({ key: p, label: p, count: byStatus.filter((u) => profileOf(u) === p).length }))} />
                <FilterChips title="User Status" value={userStatus} onChange={setUserStatus}
                  options={[
                    { key: 'active', label: 'Active', tone: 'good', count: byProfile.filter((u) => statusOf(u) === 'active').length },
                    { key: 'inactive', label: 'Inactive', tone: 'bad', count: byProfile.filter((u) => statusOf(u) === 'inactive').length },
                  ]} />
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-ink-muted">
                  <tr className="border-b border-line">
                    <th className="px-3 py-2 font-medium">User Name</th>
                    <th className="px-3 py-2 font-medium">Profile</th>
                    <th className="px-3 py-2 font-medium">Email</th>
                    <th className="px-3 py-2 font-medium">Title</th>
                    <th className="px-3 py-2 font-medium">Phone</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {!shown.length && (
                    <tr>
                      <td colSpan={6} className="px-3 py-4 text-center text-xs text-ink-subtle">No users match these filters.</td>
                    </tr>
                  )}
                  {shown.map((u) => (
                    <tr key={u.id}>
                      <td className="px-3 py-2"><RecordLink object="User" id={u.id}>{u.name}</RecordLink></td>
                      <td className="px-3 py-2 text-ink-muted">{u.profile ?? '—'}</td>
                      <td className="px-3 py-2 text-ink-muted">
                        {u.email ? <a href={`mailto:${u.email}`} className="hover:text-brand hover:underline">{u.email}</a> : '—'}
                      </td>
                      <td className="px-3 py-2 text-ink-muted">{u.title || '—'}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-ink-muted">{u.phone || '—'}</td>
                      <td className="px-3 py-2">
                        <span
                          className={cx(
                            'rounded-full px-2 py-0.5 text-xs font-medium',
                            u.tone === 'bad' ? 'bg-bad-soft text-bad' : u.tone === 'warn' ? 'bg-warn-soft text-warn' : 'bg-good-soft text-good',
                          )}
                        >
                          {u.status}
                        </span>
                        {/* whether, and when, they last logged in to Salesforce */}
                        {u.login && <span className="mt-1 block text-[11px] text-ink-subtle">{u.login}</span>}
                        {/* what EAC does for them: Master status, then Email, Calendar and Contact sync */}
                        {u.sync && u.sync.length > 0 && (
                          <ul className="mt-1.5 space-y-0.5 text-[11px]">
                            {u.sync.map((s) => (
                              <li key={s.key} className="flex items-center justify-between gap-3" title={s.source}>
                                <span className="text-ink-muted">{s.label}</span>
                                <span
                                  className={cx(
                                    'rounded-full px-1.5 font-medium',
                                    s.on == null ? 'bg-muted text-ink-subtle' : s.on ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad',
                                  )}
                                >
                                  {s.on == null ? 'Not available' : s.on ? 'Enabled' : 'Disabled'}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
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
