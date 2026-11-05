import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Clock, GitBranch, Layers, User, Users, X } from 'lucide-react';
import { indicatorApi } from '@/api/endpoints';
import { InfoTip } from '@/components/ui/HelpTip';
import { cx, fmtNumber } from '@/lib/format';

export type PickedQueue = { id: string; name: string };

/** Stuck Queue-Owned Leads: how long a Lead has waited in its queue to be listed (0 = every Lead in a queue). */
export const QUEUE_DAYS = [3, 5, 7] as const;

export function QueueDays({ value, onChange }: { value: number; onChange: (days: number) => void }) {
  const chip = (days: number, text: string) => (
    <button
      key={days}
      type="button"
      aria-pressed={value === days}
      onClick={() => onChange(days)}
      className={cx(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-xs transition',
        value === days ? 'border-brand bg-brand-soft font-semibold text-brand-ink' : 'border-line hover:border-brand/40 hover:text-brand',
      )}
    >
      {text}
    </button>
  );
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Days in queue">
      <span className="mr-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        <Clock className="h-3.5 w-3.5" /> In a queue
      </span>
      {QUEUE_DAYS.map((d) => chip(d, `More than ${d} days`))}
      {chip(0, 'Any time')}
    </div>
  );
}

/** Every Lead queue in the org side by side above the records (Stuck Queue-Owned Leads, Inactive Lead Assignment Rules), with
 *  how many of the card's Leads sit in each. Clicking one shows only its Leads; "All" (or clicking it again) shows every queue's. */
export function QueueFilter({
  assessmentId,
  areaId,
  label,
  object,
  value,
  days,
  period,
  onChange,
  title = 'Lead queues',
  tip,
  empty = 'No Lead queues found.',
}: {
  assessmentId: string;
  areaId: string;
  label: string;
  object: string;
  value: PickedQueue | undefined;
  /** Stuck Queue-Owned Leads: the days-in-queue threshold picked (the counts follow it). */
  days?: number;
  /** Stale Leads: the period picked on the card (the counts follow it). */
  period?: string;
  onChange: (queue: PickedQueue | undefined) => void;
  /** The chips' heading, what it means, and what to say when there are none. */
  title?: string;
  tip?: string;
  empty?: string;
}) {
  const queues = useQuery({
    queryKey: ['indicator-queues', assessmentId, areaId, label, object, days, period],
    queryFn: ({ signal }) => indicatorApi.queues(assessmentId, areaId, label, object, signal, days, period),
    staleTime: 60_000,
  });
  const list = queues.data ?? [];
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={title}>
      <span className="mr-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        <Users className="h-3.5 w-3.5" /> {title}
        <InfoTip label={`About ${title}`}>
          {tip ?? 'Green: the active Lead Assignment Rule assigns to the queue. Red: no active rule does. Pick a queue to see only its Leads.'}
        </InfoTip>
      </span>
      {queues.isLoading ? (
        <span className="text-xs text-ink-subtle">Loading…</span>
      ) : queues.error ? (
        <span className="text-xs text-bad">Couldn’t load them.</span>
      ) : !list.length ? (
        <span className="text-xs text-ink-subtle">{empty}</span>
      ) : (
        [
          <button
            key="all"
            type="button"
            aria-pressed={!value}
            onClick={() => onChange(undefined)}
            title="Show every queue’s Leads"
            className={cx(
              'inline-flex items-center rounded-full border px-2.5 py-1 text-xs transition',
              !value ? 'border-brand bg-brand-soft font-semibold text-brand-ink' : 'border-line hover:border-brand/40 hover:text-brand',
            )}
          >
            All
          </button>,
          ...list.map((q) => {
          const on = value?.id === q.id;
          return (
            <button
              key={q.id}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(on ? undefined : { id: q.id, name: q.name })}
              title={(q.active ? 'The active Lead Assignment Rule assigns to this queue. ' : q.active === false ? 'No active Lead Assignment Rule assigns to this queue. ' : '')
                + (on ? 'Show every queue’s Leads' : `Show only the Leads in ${q.name}`)}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition',
                on ? 'border-brand bg-brand-soft font-semibold text-brand-ink' : 'border-line hover:border-brand/40 hover:text-brand',
                !on && !q.count && 'text-ink-subtle',
              )}
            >
              {q.name}
              {/* green: the active rule assigns to the queue; red: no active rule does */}
              <span className={cx('rounded-full px-1.5 tabular-nums', on ? 'bg-surface' : q.count ? (q.active ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad') : 'bg-muted')}>{fmtNumber(q.count)}</span>
              {on && <X className="h-3 w-3" aria-hidden="true" />}
            </button>
          );
          }),
        ]
      )}
    </div>
  );
}

const chipClass = (on: boolean, muted = false) =>
  cx(
    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition disabled:cursor-not-allowed disabled:opacity-50',
    on ? 'border-brand bg-brand-soft font-semibold text-brand-ink' : 'border-line hover:border-brand/40 hover:text-brand',
    !on && muted && 'text-ink-subtle',
  );

const countClass = (on: boolean, n: number) => cx('rounded-full px-1.5 tabular-nums', on ? 'bg-surface' : n ? 'bg-bad-soft text-bad' : 'bg-muted');

function ChipRow({ icon, title, tip, children }: { icon: React.ReactNode; title: string; tip: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={title}>
      <span className="mr-1 inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        {icon} {title}
        <InfoTip label={`About ${title}`}>{tip}</InfoTip>
      </span>
      {children}
    </div>
  );
}

/** Inactive Lead Assignment Rules: the inactive rules, then who they assign to (queues and users), above the records.
 *  Picking a rule shows only its queues and users (and the Leads they own); picking one of those shows only its Leads.
 *  "All" on either row goes back a step. The picked owners reach the table as `value` (one id, or a rule's ids joined by commas). */
export function RuleTargetFilter({
  assessmentId,
  areaId,
  label,
  object,
  value,
  onChange,
}: {
  assessmentId: string;
  areaId: string;
  label: string;
  object: string;
  value: PickedQueue | undefined;
  onChange: (queue: PickedQueue | undefined) => void;
}) {
  const [rule, setRule] = useState<string | undefined>();
  const data = useQuery({
    queryKey: ['indicator-rule-targets', assessmentId, areaId, label, object],
    queryFn: ({ signal }) => indicatorApi.ruleTargets(assessmentId, areaId, label, object, signal),
    staleTime: 60_000,
  });
  const rules = data.data?.rules ?? [];
  const picked = rules.find((r) => r.name === rule);
  const targets = (data.data?.targets ?? []).filter((t) => !picked || picked.targets.includes(t.id));
  const ruleLevel = (r: { name: string; targets: string[] }) => ({ id: r.targets.join(','), name: r.name });
  const pickRule = (name: string | undefined) => {
    const r = rules.find((x) => x.name === name);
    setRule(r?.name);
    onChange(r ? ruleLevel(r) : undefined);
  };
  const pickTarget = (t: { id: string; name: string } | undefined) => {
    if (!t || value?.id === t.id) onChange(picked ? ruleLevel(picked) : undefined);
    else onChange({ id: t.id, name: t.name });
  };
  const targetPicked = !!value && !value.id.includes(',') && targets.some((t) => t.id === value.id);
  if (data.isLoading) return <span className="text-xs text-ink-subtle">Loading rules and queues…</span>;
  if (data.error) return <span className="text-xs text-bad">Couldn’t load the rules and queues.</span>;
  return (
    <div className="space-y-2">
      <ChipRow
        icon={<GitBranch className="h-3.5 w-3.5" />}
        title="Inactive assignment rules"
        tip="The Lead Assignment Rules that are turned off, each with how many open Leads its queues and users own now. Pick one to see only who it assigns to."
      >
        {!rules.length ? (
          <span className="text-xs text-ink-subtle">No inactive Lead Assignment Rules in this check (run a new check if there should be some).</span>
        ) : (
          [
            <button key="all" type="button" aria-pressed={!picked} onClick={() => pickRule(undefined)} title="Show every rule’s queues and users" className={chipClass(!picked)}>
              All
            </button>,
            ...rules.map((r) => {
              const on = picked?.name === r.name;
              return (
                <button
                  key={r.name}
                  type="button"
                  aria-pressed={on}
                  disabled={!r.targets.length}
                  onClick={() => pickRule(on ? undefined : r.name)}
                  title={!r.targets.length ? 'This rule assigns to no queue or user we could find' : on ? 'Show every rule’s queues and users' : `Show only who “${r.name}” assigns to`}
                  className={chipClass(on, !r.count)}
                >
                  {r.name}
                  <span className={countClass(on, r.count)}>{fmtNumber(r.count)}</span>
                  {on && <X className="h-3 w-3" aria-hidden="true" />}
                </button>
              );
            }),
          ]
        )}
      </ChipRow>
      <ChipRow
        icon={<Users className="h-3.5 w-3.5" />}
        title="Assigned to"
        tip={
          picked
            ? `The queues and users “${picked.name}” assigns to, each with how many open Leads it owns now. Pick one to see only its Leads.`
            : 'Every inactive rule’s queues and users, and the Lead queues the active rule never assigns to (inactive queues), each with how many open Leads it owns now. Pick one to see only its Leads.'
        }
      >
        {!targets.length ? (
          <span className="text-xs text-ink-subtle">No queues or users to show.</span>
        ) : (
          [
            <button key="all" type="button" aria-pressed={!targetPicked} onClick={() => pickTarget(undefined)} title={picked ? `Show the Leads of everyone “${picked.name}” assigns to` : 'Show the Leads in the inactive Lead queues'} className={chipClass(!targetPicked)}>
              All
            </button>,
            ...targets.map((t) => {
              const on = targetPicked && value?.id === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => pickTarget(t)}
                  title={`${t.type === 'User' ? 'User' : t.inactive ? 'Queue (inactive: out of the active routing)' : 'Queue'} — ${on ? 'click again to show all' : `show only the Leads ${t.name} owns`}`}
                  className={chipClass(on, !t.count)}
                >
                  {t.type === 'User' ? <User className="h-3 w-3" aria-hidden="true" /> : <Users className="h-3 w-3" aria-hidden="true" />}
                  {t.name}
                  <span className={countClass(on, t.count)}>{fmtNumber(t.count)}</span>
                  {on && <X className="h-3 w-3" aria-hidden="true" />}
                </button>
              );
            }),
          ]
        )}
      </ChipRow>
    </div>
  );
}

/** One labelled drop-down of the Stale Leads filters: "All" first, then each value with its count. */
function CountSelect({
  icon,
  title,
  tip,
  allText,
  value,
  options,
  loading,
  error,
  empty,
  onChange,
}: {
  icon: React.ReactNode;
  title: string;
  tip: string;
  allText: string;
  value: string | undefined;
  options: { id: string; name: string; count: number }[];
  loading: boolean;
  error: boolean;
  empty: string;
  onChange: (picked: PickedQueue | undefined) => void;
}) {
  const total = options.reduce((n, o) => n + o.count, 0);
  return (
    <label className="inline-flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        {icon} {title}
        <InfoTip label={`About ${title}`}>{tip}</InfoTip>
      </span>
      {loading ? (
        <span className="text-xs text-ink-subtle">Loading…</span>
      ) : error ? (
        <span className="text-xs text-bad">Couldn’t load them.</span>
      ) : !options.length ? (
        <span className="text-xs text-ink-subtle">{empty}</span>
      ) : (
        <select
          value={value ?? ''}
          onChange={(e) => {
            const o = options.find((x) => x.id === e.target.value);
            onChange(o ? { id: o.id, name: o.name } : undefined);
          }}
          className="min-w-[12rem] rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs text-ink focus:border-brand focus:outline-none"
        >
          <option value="">{`${allText} (${fmtNumber(total)})`}</option>
          {options.map((o) => (
            <option key={o.id} value={o.id}>{`${o.name} (${fmtNumber(o.count)})`}</option>
          ))}
        </select>
      )}
    </label>
  );
}

/** Stale Leads: Record Type, then the Status the Leads are stuck in, as drop-downs above the records. Picking a record type
 *  lists only the Statuses its stale Leads are stuck in (and their counts); both follow the period picked on the table. */
export function StaleFilters({
  assessmentId,
  areaId,
  label,
  object,
  period,
  recordType,
  onRecordType,
  status,
  onStatus,
}: {
  assessmentId: string;
  areaId: string;
  label: string;
  object: string;
  period?: string;
  recordType: PickedQueue | undefined;
  onRecordType: (rt: PickedQueue | undefined) => void;
  status: PickedQueue | undefined;
  onStatus: (s: PickedQueue | undefined) => void;
}) {
  const types = useQuery({
    queryKey: ['indicator-record-types', assessmentId, areaId, label, object, period],
    queryFn: ({ signal }) => indicatorApi.recordTypes(assessmentId, areaId, label, object, signal, period),
    staleTime: 60_000,
  });
  const statuses = useQuery({
    queryKey: ['indicator-queues', assessmentId, areaId, label, object, undefined, period, recordType?.id],
    queryFn: ({ signal }) => indicatorApi.queues(assessmentId, areaId, label, object, signal, undefined, period, recordType?.id),
    staleTime: 60_000,
  });
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      <CountSelect
        icon={<Layers className="h-3.5 w-3.5" />}
        title="Record Type"
        tip="The Lead record types, each with how many stale Leads have it (for the period picked on the table). Pick one to see only its Leads and the Statuses they are stuck in."
        allText="All record types"
        value={recordType?.id}
        options={types.data ?? []}
        loading={types.isLoading}
        error={!!types.error}
        empty="Leads have no record types."
        onChange={onRecordType}
      />
      <CountSelect
        icon={<Users className="h-3.5 w-3.5" />}
        title="Stuck in Status"
        tip={`The Status each stale Lead${recordType ? ` of “${recordType.name}”` : ''} is stuck in, with how many Leads (for the period picked on the table). Pick one to see only those Leads.`}
        allText="All statuses"
        value={status?.id}
        options={statuses.data ?? []}
        loading={statuses.isLoading}
        error={!!statuses.error}
        empty={recordType ? 'No stale Leads of this record type in this period.' : 'No stale Leads in this period.'}
        onChange={onStatus}
      />
    </div>
  );
}
