import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { indicatorApi, type RepActivityRep } from '@/api/endpoints';
import { LocalTable, type LocalColumn } from '@/components/data/LocalTable';
import { RecordLink } from '@/components/data/RecordLink';
import { cx, fmtNumber } from '@/lib/format';
import { FilterChips } from './EacHealth';

const PERIODS = [7, 14, 30, 90] as const;
const TYPES = [
  { key: 'email', label: 'Emails' },
  { key: 'event', label: 'Events' },
  { key: 'task', label: 'Tasks' },
] as const;
const NO_PROFILE = '(no profile)';

/** YYYY-MM-DD in the viewer's own time zone (what a date input shows). */
const day = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return day(d);
};

/** Reps with No Activities Logged Recently: every rep (people who own open deals or leads) with their Profile, and how many
 *  Emails, Events and Tasks they logged in the period, read live from Salesforce, those who logged nothing first. The Profile
 *  chips narrow the reps; the Period is the last 7, 14, 30 or 90 days, or custom dates. */
export function RepActivity({ assessmentId }: { assessmentId: string }) {
  const today = day(new Date());
  const [choice, setChoice] = useState<string>('30'); // a number of days, or "custom"
  const [from, setFrom] = useState(daysAgo(60));
  const [to, setTo] = useState(daysAgo(30));
  // the period asked for: the custom dates only once both make sense (until then, the last good one stays)
  const [period, setPeriod] = useState<number | { from: string; to: string }>(30);
  const valid = (f: string, t: string) => !!f && !!t && f <= t && f <= today;
  const pick = (c: string, f = from, t = to) => {
    setChoice(c);
    if (c !== 'custom') setPeriod(Number(c));
    else if (valid(f, t)) setPeriod({ from: f, to: t });
  };
  const [profile, setProfile] = useState<string | undefined>();
  const data = useQuery({
    queryKey: ['rep-activity', assessmentId, period],
    queryFn: ({ signal }) => indicatorApi.repActivity(assessmentId, period, signal),
    staleTime: 60_000,
  });
  if (data.isLoading) return <p className="text-sm text-ink-subtle">Reading reps’ activity from Salesforce…</p>;
  if (data.error) return <p className="rounded-lg bg-bad-soft/50 px-4 py-3 text-sm text-bad">Couldn’t read reps’ activity: {(data.error as Error).message}</p>;
  const d = data.data!;
  const reps = d.reps;
  const profileOf = (r: RepActivityRep) => r.profile ?? NO_PROFILE;
  const quiet = (r: RepActivityRep) => !r.counts.email && !r.counts.event && !r.counts.task;
  const shown = reps.filter((r) => !profile || profileOf(r) === profile);
  const profiles = [...new Set([...reps.map(profileOf), ...(profile ? [profile] : [])])].sort((a, b) => a.localeCompare(b));
  const columns: LocalColumn<RepActivityRep>[] = [
    { key: 'name', label: 'User Name', value: (r) => r.name, render: (r) => <RecordLink object="User" id={r.id}>{r.name}</RecordLink> },
    { key: 'profile', label: 'Profile', value: (r) => r.profile, className: 'text-ink-muted' },
    {
      key: 'email',
      label: 'Email',
      value: (r) => r.email,
      className: 'text-ink-muted',
      render: (r) => (r.email ? <a href={`mailto:${r.email}`} className="hover:text-brand hover:underline">{r.email}</a> : '—'),
    },
    { key: 'title', label: 'Title', value: (r) => r.title, className: 'text-ink-muted' },
    ...TYPES.map((t): LocalColumn<RepActivityRep> => ({
      key: t.key,
      label: t.label,
      align: 'right',
      value: (r) => (d.available[t.key] ? r.counts[t.key] : null),
      render: (r) =>
        !d.available[t.key] ? (
          <span className="text-ink-subtle">—</span>
        ) : (
          <span className={cx('rounded-full px-1.5', r.counts[t.key] ? 'text-ink' : 'bg-bad-soft text-bad')}>{fmtNumber(r.counts[t.key])}</span>
        ),
    })),
    {
      key: 'lastActivity',
      label: 'Last activity',
      value: (r) => r.lastActivity,
      className: 'whitespace-nowrap text-ink-muted',
      render: (r) => r.lastActivity ?? 'None in the period',
    },
  ];
  const span = typeof period === 'number' ? `in the last ${period} days` : `from ${period.from} to ${period.to}`;

  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-muted">
        {fmtNumber(shown.filter(quiet).length)} of {fmtNumber(shown.length)} reps logged no activity {span}
      </p>
      <div className="space-y-1.5 rounded-xl border border-line px-3 py-2">
        <FilterChips
          title="Profile"
          value={profile}
          onChange={setProfile}
          options={profiles.map((p) => ({ key: p, label: p, count: reps.filter((r) => profileOf(r) === p).length }))}
        />
        {/* the period the activity counts cover: the last 7 to 90 days, or custom dates (both included) */}
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted" role="group" aria-label="Period">
          <span className="mr-1 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">Period</span>
          <select
            value={choice}
            onChange={(e) => pick(e.target.value)}
            aria-label="Period"
            className="rounded-lg border border-line bg-surface px-2.5 py-1 text-xs text-ink focus:border-brand focus:outline-none"
          >
            {PERIODS.map((p) => (
              <option key={p} value={String(p)}>
                Last {p} days
              </option>
            ))}
            <option value="custom">Custom dates…</option>
          </select>
          {choice === 'custom' && (
            <>
              <span>From</span>
              <input
                type="date"
                value={from}
                max={to || today}
                onChange={(e) => {
                  setFrom(e.target.value);
                  pick('custom', e.target.value, to);
                }}
                aria-label="From"
                className="rounded-lg border border-line bg-surface px-2 py-1 text-xs text-ink focus:border-brand focus:outline-none"
              />
              <span>to</span>
              <input
                type="date"
                value={to}
                min={from || undefined}
                max={today}
                onChange={(e) => {
                  setTo(e.target.value);
                  pick('custom', from, e.target.value);
                }}
                aria-label="To"
                className="rounded-lg border border-line bg-surface px-2 py-1 text-xs text-ink focus:border-brand focus:outline-none"
              />
              {!valid(from, to) && <span className="text-bad">From must be on or before To</span>}
            </>
          )}
        </div>
      </div>
      <LocalTable
        title="Reps and what they logged"
        rows={shown}
        columns={columns}
        rowKey={(r) => r.id}
        empty="No reps found: nobody active owns open deals or leads."
      />
      <p className="text-[11px] text-ink-subtle">
        Read live from Salesforce. Emails are logged emails (Tasks with Task Subtype Email); Tasks are the other Tasks; Events are calendar
        events. Reps are active users who own an open Opportunity or Lead.
      </p>
    </div>
  );
}
