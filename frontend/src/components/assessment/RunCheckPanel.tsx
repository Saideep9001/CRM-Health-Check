import { motion } from 'framer-motion';
import { CheckCircle2, Info, Link2, Loader2, Play, Plus, RotateCcw, Square, TriangleAlert, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  useApiHealth,
  useAssessment,
  useAssessments,
  useCancelAssessment,
  useConnection,
  useCreateAssessment,
  useDataObjects,
  useRole,
} from '@/api/queries';
import { isApiError } from '@/api/client';
import { ObjectChooser } from '@/components/data/ObjectList';
import { Button, LinkButton } from '@/components/ui/Button';
import { Select } from '@/components/ui/Form';
import { Notice } from '@/components/ui/Page';
import { InlineError } from '@/components/ui/States';
import { CATEGORIES, MVP_AREA_IDS } from '@/config/categories';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDate } from '@/lib/format';

type DayOption = '7' | '14' | '30' | '60' | '90';
const dayOptions = (prefix: string): { value: DayOption; label: string }[] =>
  (['7', '14', '30', '60', '90'] as DayOption[]).map((d) => ({ value: d, label: `${prefix} ${d} days` }));

/** Objects Data Quality checks by default; users can pick others (any object in their org). */
export const DEFAULT_DQ_OBJECTS = ['Account', 'Contact', 'Lead', 'Opportunity'];
const MAX_OBJECTS = 15;
const DQ_AREAS = new Set(CATEGORIES.find((c) => c.id === 'data-quality')?.areaIds ?? []);
const OBJECTS_KEY = 'aq.dq.objects';

function loadObjects(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(OBJECTS_KEY) ?? 'null') as unknown;
    if (Array.isArray(v) && v.length && v.every((x) => typeof x === 'string')) return (v as string[]).slice(0, MAX_OBJECTS);
  } catch {
    // Storage blocked or bad data: use the defaults.
  }
  return DEFAULT_DQ_OBJECTS;
}

function saveObjects(v: string[]) {
  try {
    localStorage.setItem(OBJECTS_KEY, JSON.stringify(v));
  } catch {
    // The choice just won't be remembered.
  }
}

/**
 * Start a health check right where the user is (topic, area, or overview page),
 * then show live progress and the outcome in place. No separate wizard.
 */
export function RunCheckPanel({
  areaIds,
  label,
  checked,
  lastChecked,
  objectPicker = false,
  lastObjects: lastObjectsProp,
}: {
  /** Areas this panel checks; only the ones the engine can run are used. */
  areaIds: string[];
  /** e.g. "this topic", "this area", "everything" */
  label: string;
  /** Whether these areas already have results (shows a compact "Check again" bar). */
  checked: boolean;
  lastChecked?: string | null;
  /** Let the user choose which Salesforce objects the Data Quality checks look at. */
  objectPicker?: boolean;
  /** Objects the check behind the shown results looked at (else the latest finished check of these areas). */
  lastObjects?: string[] | null;
}) {
  const { canEdit } = useRole();
  const conn = useConnection();
  const health = useApiHealth();
  const list = useAssessments();
  const create = useCreateAssessment();
  const cancel = useCancelAssessment();
  const { notify } = useToast();
  const [staleDays, setStaleDays] = useState<DayOption>('30');
  const [stuckDays, setStuckDays] = useState<DayOption>('60');
  const [startedId, setStartedId] = useState<string | null>(null);
  const [chosen, setObjects] = useState<string[]>(loadObjects);
  const [chooserOpen, setChooserOpen] = useState(false);
  const updateObjects = (v: string[]) => {
    setObjects(v);
    saveObjects(v);
  };

  const runnable = useMemo(() => {
    const engine = health.data?.executableAreaIds ?? MVP_AREA_IDS;
    return areaIds.filter((id) => engine.includes(id));
  }, [areaIds, health.data]);

  const active = list.data?.find((a) => a.status === 'queued' || a.status === 'running') ?? null;
  const watchId = active?.id ?? startedId;
  const watched = useAssessment(watchId);
  const run = watched.data ?? active;
  const running = !!run && (run.status === 'queued' || run.status === 'running');
  // Started elsewhere (another tab or person) and this page hadn't seen it yet: not an error, so fetch it and show its progress.
  const busy = isApiError(create.error) && create.error.status === 409 && /already running/i.test(create.error.message);
  useEffect(() => {
    if (busy) list.refetch();
  }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (running && create.error) create.reset();
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  // Tell the user once when the check they started here finishes.
  const announced = useRef<string | null>(null);
  useEffect(() => {
    const a = watched.data;
    if (!a || a.id !== startedId || announced.current === a.id) return;
    if (a.status === 'completed') {
      announced.current = a.id;
      notify('Health check finished', `${a.findingsCount ?? 0} problems found. Results are shown below.`, 'success');
    } else if (a.status === 'failed') {
      announced.current = a.id;
      notify('Health check failed', a.errorMessage ?? undefined, 'warning');
    }
  }, [watched.data, startedId, notify]);

  const connected = conn.data?.status === 'connected';
  const checksObjects = runnable.some((id) => DQ_AREAS.has(id));
  const usesStale = runnable.includes('area-3');
  const usesStuck = runnable.includes('area-5') || runnable.includes('area-10');
  const orgObjects = useDataObjects(connected && objectPicker && checksObjects);
  const labels = useMemo(() => new Map((orgObjects.data ?? []).map((o) => [o.name, o.labelPlural])), [orgObjects.data]);
  // Uploaded CSV/Excel data: only the objects that were uploaded (the saved choice is for Salesforce orgs).
  const uploaded = conn.data?.environment === 'upload' && orgObjects.data?.length ? orgObjects.data.map((o) => o.name) : null;
  const inUpload = uploaded ? chosen.filter((o) => uploaded.includes(o)) : chosen;
  const objects = uploaded ? (inUpload.length ? inUpload : uploaded.slice(0, MAX_OBJECTS)) : chosen;
  const isDefault = objects.length === DEFAULT_DQ_OBJECTS.length && DEFAULT_DQ_OBJECTS.every((o) => objects.includes(o));
  // The objects the last finished check of these areas looked at; results on this page come from that check.
  const lastRun = list.data?.find((a) => a.status === 'completed' && a.scope.areaIds?.some((id) => runnable.includes(id))) ?? null;
  const lastObjects = lastObjectsProp ?? (lastRun ? (lastRun.scope.objects?.length ? lastRun.scope.objects : DEFAULT_DQ_OBJECTS) : null);
  const selectionPending = !!lastObjects && (lastObjects.length !== objects.length || objects.some((o) => !lastObjects.includes(o)));

  const start = () => {
    if (!conn.data?.id || runnable.length === 0) return;
    const categoryIds = CATEGORIES.filter((c) => c.areaIds.some((id) => runnable.includes(id))).map((c) => c.id);
    const names = categoryIds.map((id) => CATEGORIES.find((c) => c.id === id)!.shortName).join(' & ');
    create.mutate(
      {
        name: `${names} check — ${fmtDate(new Date().toISOString())}`,
        connectionId: conn.data.id,
        scope: {
          categoryIds,
          areaIds: runnable,
          lookbackDays: null, // every record is checked
          staleLeadDays: Number(staleDays),
          stuckOpportunityDays: Number(stuckDays),
          objects: checksObjects ? objects : undefined,
        },
      },
      { onSuccess: (a) => setStartedId(a.id) },
    );
  };

  if (!canEdit && !running) {
    return checked ? null : (
      <p className="mb-6 rounded-xl border border-line bg-muted/50 px-4 py-3 text-sm text-ink-muted">
        You have view-only access, so you can’t start a health check. Ask a consultant or admin to run one.
      </p>
    );
  }

  // ---- running: live progress
  if (running && run) {
    const done = run.progress ?? 0;
    const since = Date.parse(run.startedAt ?? run.createdAt);
    const secs = Number.isFinite(since) ? Math.max(0, Math.round((now - since) / 1000)) : null;
    const elapsed = secs == null ? null : secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, '0')}s`;
    const step = run.currentStep ?? (run.status === 'queued' ? 'Waiting to start' : 'Starting');
    return (
      <div className="mb-6 rounded-lg border border-brand/20 bg-brand-soft/60 px-3 py-2" role="status" aria-live="polite">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-brand" />
          <span className="min-w-0 flex-1 truncate text-ink" title={step}>
            <span className="font-semibold">{step}</span>
          </span>
          <span className="flex w-full items-center gap-2 sm:w-56">
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
              <motion.span className="block h-full rounded-full bg-brand" initial={false} animate={{ width: `${Math.max(done, 2)}%` }} transition={{ duration: 0.6 }} />
            </span>
            <span className="w-9 text-right font-semibold tabular-nums text-brand">{done}%</span>
          </span>
          {elapsed && <span className="tabular-nums text-ink-subtle">{elapsed}</span>}
          <button type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(run.id)}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-ink-muted hover:bg-surface hover:text-ink disabled:opacity-50">
            <Square className="h-3 w-3" /> {cancel.isPending ? 'Stopping…' : 'Stop'}
          </button>
        </div>
        <InlineError error={cancel.error} />
      </div>
    );
  }

  if (runnable.length === 0) return null;

  if (conn.isSuccess && !connected) {
    return (
      <Notice
        title="Connect Salesforce first."
        action={
          <LinkButton to="/connection" size="sm" variant="primary" icon={<Link2 className="h-3.5 w-3.5" />}>
            Connect Salesforce
          </LinkButton>
        }
      >
        Then you can check {label} here.
      </Notice>
    );
  }

  const failed = watched.data?.id === startedId && watched.data?.status === 'failed' ? watched.data : null;
  const controls = (
    <div className="flex flex-wrap items-center gap-2">
      {usesStale && (
        <Select<DayOption> label="When is a lead stale?" value={staleDays} onChange={setStaleDays} options={dayOptions('Stale lead after')} className="w-full sm:w-48" />
      )}
      {usesStuck && (
        <Select<DayOption> label="When is a deal stuck?" value={stuckDays} onChange={setStuckDays} options={dayOptions('Stuck deal after')} className="w-full sm:w-48" />
      )}
      <Button
        size="sm"
        variant="primary"
        icon={checked ? <RotateCcw className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        disabled={create.isPending || !connected}
        onClick={start}
      >
        {create.isPending ? 'Starting…' : checked ? 'Check again' : `Check ${label}`}
      </Button>
    </div>
  );

  const objectRow = objectPicker && checksObjects && connected && (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line/70 pt-3">
      <span className="mr-1 text-xs font-medium text-ink-muted" title="Choose the objects the next check looks at. To see results for an object, use the object buttons on each area below.">
        Objects for the next check:
      </span>
      {objects.map((o) => (
        <span key={o} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface py-0.5 pl-2.5 pr-1 text-xs font-medium">
          {labels.get(o) ?? o}
          <button
            onClick={() => updateObjects(objects.filter((x) => x !== o))}
            disabled={objects.length === 1}
            className="rounded-full p-0.5 text-ink-subtle hover:bg-muted hover:text-ink disabled:opacity-30"
            aria-label={`Don’t check ${labels.get(o) ?? o}`}
            title={objects.length === 1 ? 'Keep at least one object' : 'Remove'}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setChooserOpen(true)} disabled={!orgObjects.data}>
        Add or change
      </Button>
      {!isDefault && (
        <button className="text-xs font-medium text-brand hover:underline" onClick={() => updateObjects(DEFAULT_DQ_OBJECTS)}>
          Reset
        </button>
      )}
      {orgObjects.data && (
        <ObjectChooser
          open={chooserOpen}
          onClose={() => setChooserOpen(false)}
          objects={orgObjects.data}
          value={objects}
          onSave={updateObjects}
          title="Choose objects to check"
          description="The Data Quality check looks only at these. Other objects get general checks: duplicates, missing details, and unused fields."
          max={MAX_OBJECTS}
          allowEmpty={false}
        />
      )}
      {checked && selectionPending && !running && (
        <p className="basis-full pt-1 text-xs text-warn">
          Results below are from the last check, which looked at {lastObjects!.map((o) => labels.get(o) ?? o).join(', ')}. Click{' '}
          <span className="font-semibold">Check again</span> to check only the objects chosen here.
        </p>
      )}
    </div>
  );

  return (
    <>
      {failed && (
        <Notice tone="warn" icon={<TriangleAlert className="h-4 w-4" />} title="The last check didn’t finish.">
          {failed.errorMessage ?? 'Please try again.'}
        </Notice>
      )}
      <div className={cx('mb-6 rounded-xl border px-4 py-3 text-sm', checked ? 'border-line bg-muted' : 'border-brand/25 bg-brand-soft')}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex min-w-[14rem] flex-1 items-start gap-3">
            <span className="mt-0.5 shrink-0">
              {checked ? <CheckCircle2 className="h-4 w-4 text-good" /> : <Info className="h-4 w-4 text-brand" />}
            </span>
            <p className="text-ink-muted">
              <span className="font-semibold text-ink">{checked ? 'Checked. ' : 'Not checked yet. '}</span>
              {checked ? (lastChecked ? `Last checked ${fmtDate(lastChecked)}.` : 'Run it again to see the latest.') : 'Takes about a minute. We only read your data.'}
            </p>
          </div>
          <div className="min-w-0 max-w-full">{controls}</div>
        </div>
        {objectRow}
      </div>
      {busy ? (
        <div className="-mt-3 mb-6 flex items-center gap-3 rounded-xl border border-brand/20 bg-brand-soft px-4 py-3 text-sm" role="status">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand" />
          <span className="text-ink-muted">
            <span className="font-semibold text-ink">A health check is already running for this Salesforce.</span> Its progress will show here in a moment;
            when it finishes you can check again.
          </span>
        </div>
      ) : (
        <InlineError error={create.error} />
      )}
    </>
  );
}
