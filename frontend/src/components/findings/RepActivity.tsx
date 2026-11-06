import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { indicatorApi, type RepActivityRep } from '@/api/endpoints';
import { RecordLink } from '@/components/data/RecordLink';
import { cx, fmtNumber } from '@/lib/format';
import { FilterChips } from './EacHealth';

const PERIODS = [7, 14, 30, 90] as const;
const TYPES = [
  { key: 'email', label: 'Emails' },
  { key: 'event', label: 'Events' },
  { key: 'task', label: 'Tasks' },
] as const;
type TypeKey = (typeof TYPES)[number]['key'];
const NO_PROFILE = '(no profile)';

/** Reps with No Activities Logged Recently: the reps (people who own open deals or leads) with their Profile, and how many
 *  Emails, Events and Tasks they logged in the period, read live from Salesforce. The Profile and User activity chips pick
 *  which reps show: "All" = no activity of any type; Emails, Events or Tasks = none of that type. */
export function RepActivity({ assessmentId }: { assessmentId: string }) {
  const [days, setDays] = useState(30);
  const [profile, setProfile] = useState<string | undefined>();
  const [type, setType] = useState<string | undefined>();
  const data = useQuery({
    queryKey: ['rep-activity', assessmentId, days],
    queryFn: ({ signal }) => indicatorApi.repActivity(assessmentId, days, signal),
    staleTime: 60_000,
  });
  if (data.isLoading) return <p className="text-sm text-ink-subtle">Reading reps’ activity from Salesforce…</p>;
  if (data.error) return <p className="rounded-lg bg-bad-soft/50 px-4 py-3 text-sm text-bad">Couldn’t read reps’ activity: {(data.error as Error).message}</p>;
  const d = data.data!;
  const reps = d.reps;
  const profileOf = (r: RepActivityRep) => r.profile ?? NO_PROFILE;
  // quiet for the activity picked: none of that type, or ("All") none at all
  const quiet = (r: RepActivityRep, t: string | undefined) =>
    t ? !r.counts[t as TypeKey] : !r.counts.email && !r.counts.event && !r.counts.task;
  const inProfile = reps.filter((r) => !profile || profileOf(r) === profile);
  const shown = inProfile.filter((r) => quiet(r, type));
  const profiles = [...new Set([...reps.map(profileOf), ...(profile ? [profile] : [])])].sort((a, b) => a.localeCompare(b));
  const what = type ? `no ${TYPES.find((t) => t.key === type)!.label.toLowerCase()}` : 'no activity';

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-ink-muted">
          {fmtNumber(shown.length)} of {fmtNumber(inProfile.length)} reps logged {what} in the last {days} days
        </p>
        <label className="inline-flex items-center gap-2 text-xs text-ink-muted">
          Period
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs text-ink focus:border-brand focus:outline-none"
          >
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                Last {p} days
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="space-y-1.5 rounded-xl border border-line px-3 py-2">
        <FilterChips
          title="Profile"
          value={profile}
          onChange={setProfile}
          options={profiles.map((p) => ({ key: p, label: p, count: reps.filter((r) => profileOf(r) === p && quiet(r, type)).length }))}
        />
        <FilterChips
          title="User activity"
          value={type}
          onChange={setType}
          options={TYPES.map((t) => ({
            key: t.key,
            label: d.available[t.key] ? t.label : `${t.label} (not available)`,
            count: inProfile.filter((r) => quiet(r, t.key)).length,
          }))}
        />
      </div>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted/30 text-xs text-ink-muted">
            <tr className="border-b border-line">
              <th className="px-3 py-2 font-medium">User Name</th>
              <th className="px-3 py-2 font-medium">Profile</th>
              <th className="px-3 py-2 font-medium">Email</th>
              <th className="px-3 py-2 font-medium">Title</th>
              {TYPES.map((t) => (
                <th key={t.key} className="px-3 py-2 text-right font-medium">{t.label}</th>
              ))}
              <th className="px-3 py-2 font-medium">Last activity</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {!shown.length && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-xs text-ink-subtle">
                  {reps.length ? 'Every rep here logged this kind of activity in the period.' : 'No reps found: nobody active owns open deals or leads.'}
                </td>
              </tr>
            )}
            {shown.map((r) => (
              <tr key={r.id}>
                <td className="px-3 py-2"><RecordLink object="User" id={r.id}>{r.name}</RecordLink></td>
                <td className="px-3 py-2 text-ink-muted">{r.profile ?? '—'}</td>
                <td className="px-3 py-2 text-ink-muted">
                  {r.email ? <a href={`mailto:${r.email}`} className="hover:text-brand hover:underline">{r.email}</a> : '—'}
                </td>
                <td className="px-3 py-2 text-ink-muted">{r.title || '—'}</td>
                {TYPES.map((t) => (
                  <td key={t.key} className="px-3 py-2 text-right tabular-nums">
                    {!d.available[t.key] ? (
                      <span className="text-ink-subtle">—</span>
                    ) : (
                      <span className={cx('rounded-full px-1.5', r.counts[t.key] ? 'text-ink' : 'bg-bad-soft text-bad')}>{fmtNumber(r.counts[t.key])}</span>
                    )}
                  </td>
                ))}
                <td className="whitespace-nowrap px-3 py-2 text-ink-muted">{r.lastActivity ?? 'None in the period'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-ink-subtle">
        Read live from Salesforce. Emails are logged emails (Tasks with Task Subtype Email); Tasks are the other Tasks; Events are calendar
        events. Reps are active users who own an open Opportunity or Lead.
      </p>
    </div>
  );
}
