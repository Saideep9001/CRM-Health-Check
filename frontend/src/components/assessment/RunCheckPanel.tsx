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
import { ObjectChooser } from '@/components/data/ObjectList';
import { Button, LinkButton } from '@/components/ui/Button';
import { Select } from '@/components/ui/Form';
import { Notice } from '@/components/ui/Page';
import { InlineError } from '@/components/ui/States';
import { CATEGORIES, MVP_AREA_IDS } from '@/config/categories';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDate } from '@/lib/format';

type Lookback = 'all' | '90' | '180' | '365';

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

const LOOKBACK_OPTIONS: { value: Lookback; label: string }[] = [
  { value: 'all', label: 'All records' },
  { value: '90', label: 'Changed in the last 90 days' },
  { value: '180', label: 'Changed in the last 6 months' },
  { value: '365', label: 'Changed in the last year' },
];

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
  const [lookback, setLookback] = useState<Lookback>('all');
  const [staleDays, setStaleDays] = useState<DayOption>('30');
  const [stuckDays, setStuckDays] = useState<DayOption>('60');
  const [startedId, setStartedId] = useState<string | null>(null);
  const [objects, setObjects] = useState<string[]>(loadObjects);
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
          lookbackDays: lookback === 'all' ? null : Number(lookback),
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
    const pct = Math.max(3, run.progress ?? 0);
    return (
      <div className="mb-6 rounded-xl border border-brand/25 bg-brand-soft px-4 py-3" role="status" aria-live="polite">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex min-w-0 flex-1 items-start gap-3 text-sm">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-brand" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold">
                Checking your Salesforce… <span className="font-normal text-ink-muted">{run.progress ?? 0}%</span>
              </p>
              <p className="truncate text-ink-muted">{run.currentStep ?? 'Starting'}</p>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
                <motion.div className="h-full rounded-full bg-brand" initial={false} animate={{ width: `${pct}%` }} transition={{ duration: 0.6 }} />
              </div>
            </div>
          </div>
          <Button size="sm" icon={<Square className="h-3.5 w-3.5" />} disabled={cancel.isPending} onClick={() => cancel.mutate(run.id)}>
            {cancel.isPending ? 'Stopping…' : 'Stop'}
          </Button>
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
      <Select<Lookback> label="Which records to check" value={lookback} onChange={setLookback} options={LOOKBACK_OPTIONS} className="w-full sm:w-56" />
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
      <span className="mr-1 text-xs font-medium text-ink-muted">Objects to check:</span>
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
      <InlineError error={create.error} />
    </>
  );
}
