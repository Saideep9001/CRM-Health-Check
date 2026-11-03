import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CircleDollarSign,
  Database,
  ExternalLink,
  Flag,
  Info,
  Lightbulb,
  ListChecks,
  ListOrdered,
  Save,
  Search,
  Target,
  TrendingDown,
  Users,
  Wrench,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { dataApi, findingApi, indicatorApi } from '@/api/endpoints';
import { useQuery } from '@tanstack/react-query';
import { useFindingRecords, useIndicatorRecords, useRole, useUpdateFinding } from '@/api/queries';
import { SEVERITY_COLORS } from '@/components/charts/Charts';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDate, fmtDateTime, fmtNumber } from '@/lib/format';
import type { DataFilter, DiagnosticArea, DuplicateResult, FieldCheckResult, FieldScore, Finding, FindingStatus, IndicatorValue, Severity } from '@/types';
import { InfoTip } from '@/components/ui/HelpTip';
import { FINDING_STATUS_LABEL, FindingStatusBadge, SeverityBadge } from '../ui/Badges';
import { Button } from '../ui/Button';
import { Field, Select } from '../ui/Form';
import { Drawer } from '../ui/Overlay';
import { InlineError } from '../ui/States';
import { ChangeBadge } from './AffectedRecords';
import { FixPlanPanel } from './FixPlanPanel';
import { ActivityPeriod } from './ActivityPeriod';
import { RecordsTable } from './RecordsTable';
import { DuplicateResults } from './DuplicateFinder';
import { ALL } from './FieldCheck';
import { FlowSteps, fieldFlowFor, fieldFlowForRecordType, flowFor, liveFlowFor, zeroFlow, type FlowStep } from './MeasureFlow';
import { FieldListTable } from './FieldListTable';
import { FieldScoreChart, chartKindFor } from './FieldScoreChart';

/** Same thresholds the engine uses (backend/app/engine/core.py → severity_for, finding min_score). */
const PROBLEM_BELOW = 95;

const FIELD_CARD_OBJECTS: Record<string, string> = { Accounts: 'Account', Contacts: 'Contact', Leads: 'Lead', Opportunities: 'Opportunity' };
/** "Unused & Low-Completion Fields (Accounts)" → Account. */
const objectOfFieldCard = (label: string) => FIELD_CARD_OBJECTS[label.match(/\(([^)]+)\)$/)?.[1] ?? ''] ?? null;
const OTHER = '__other__';

/** Area 2: the fields behind a card, with a Record type picker above the flow — a record type's fields are the ones on its
 *  page layout; fields on no record type's layout are under "Other". The flow and the list follow the pick. */
function FieldsBehind({ indicator: v, object, flow }: { indicator: IndicatorValue; object: string | null; flow: FlowStep[] | null }) {
  const [picked, setPicked] = useState<string | null>(null); // a record type id, OTHER, or null for all
  useEffect(() => setPicked(null), [v.label]);
  const rts = useQuery({
    queryKey: ['record-types', object],
    queryFn: ({ signal }) => dataApi.recordTypes(object!, signal),
    enabled: !!object,
    staleTime: 5 * 60_000,
  });
  const items = v.fieldList ?? [];
  const data = rts.data;
  const choices = data?.recordTypes.length
    ? [...data.recordTypes.map((r) => ({ id: r.id, name: r.name, fields: new Set(r.fields) })), { id: OTHER, name: 'Other', fields: new Set(data.other) }]
    : [];
  const chosen = choices.find((c) => c.id === picked) ?? null;
  const shown = chosen ? items.filter((f) => chosen.fields.has(f.name)) : items;
  const steps = chosen && data
    ? fieldFlowForRecordType(v, { name: chosen.id === OTHER ? 'no record type’s layout' : `the ${chosen.name} layout`, fields: chosen.fields, fillable: new Set(data.fillable), ownCustom: new Set(data.ownCustom) })
    : flow;
  return (
    <>
      {choices.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs font-medium text-ink-muted">Record type</span>
          {[{ id: null as string | null, name: 'All', count: items.length }, ...choices.map((c) => ({ id: c.id as string | null, name: c.name, count: items.filter((f) => c.fields.has(f.name)).length }))].map((c) => (
            <button
              key={c.id ?? 'all'}
              type="button"
              onClick={() => setPicked(c.id)}
              title={c.id === OTHER ? 'Fields that are on no record type’s page layout' : c.id ? `Fields on the ${c.name} page layout` : 'Every field'}
              className={cx(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition',
                picked === c.id ? 'border-brand bg-brand text-white' : 'border-line bg-surface hover:border-brand/40',
              )}
            >
              {c.name}
              <span className={cx('tabular-nums', picked === c.id ? 'text-white/80' : 'text-ink-subtle')}>{fmtNumber(c.count)}</span>
            </button>
          ))}
        </div>
      )}
      {steps && (
        <div className="mb-3">
          <FlowSteps steps={steps} />
        </div>
      )}
      <FieldListTable
        items={shown}
        all={items}
        id={`${v.label}|${picked ?? 'all'}`}
        recordTypesOf={
          data?.recordTypes.length
            ? (f) => {
                // a record type's page in Setup, next to the object's field pages
                const base = Object.values(data.setupLinks ?? {})[0]?.replace(/\/FieldsAndRelationships\/.*$/, '');
                return data.recordTypes.filter((r) => r.fields.includes(f)).map((r) => ({ name: r.name, link: base ? `${base}/RecordTypes/${r.id}/view` : undefined }));
              }
            : undefined
        }
        linkOf={data ? (f) => data.setupLinks?.[f] : undefined}
      />
    </>
  );
}

/** Several fields' duplicate groups from Check fields as one result (largest groups first). */
function mergeDuplicates(check: FieldCheckResult, picked: string[]): DuplicateResult | null {
  const parts = [
    ...check.fields.filter((f) => picked.includes(f.name) && f.duplicates).map((f) => f.duplicates!),
    ...(picked.includes(ALL) && check.combined ? [check.combined] : []),
  ];
  if (!parts.length) return null;
  const columns = parts.flatMap((p) => p.columns).filter((c, i, cols) => cols.findIndex((x) => x.name === c.name) === i);
  const groups = parts.flatMap((p) => p.groups).sort((a, b) => b.size - a.size);
  // Several fields: a record can be in a group for each field. When every group is here, count each record once and
  // keep one record per set of linked groups, so the totals never pass the number of records.
  let counts: Pick<DuplicateResult, 'extraCopies' | 'kept'> = { extraCopies: parts.reduce((n, p) => n + p.extraCopies, 0) };
  if (parts.length > 1 && parts.every((p) => p.groups.length === p.totalGroups) && groups.every((g) => g.records.every((r) => r.id))) {
    const up = new Map<string, string>();
    const root = (x: string): string => {
      const p = up.get(x) ?? x;
      if (p === x) return x;
      const r = root(p);
      up.set(x, r);
      return r;
    };
    for (const g of groups) {
      const first = root(g.records[0].id!);
      for (const r of g.records) up.set(root(r.id!), first);
    }
    const ids = [...new Set(groups.flatMap((g) => g.records.map((r) => r.id!)))];
    const sets = new Set(ids.map(root)).size;
    counts = { extraCopies: ids.length - sets, kept: sets };
  }
  return {
    ...parts[0],
    rules: parts.flatMap((p) => p.rules),
    methods: parts.flatMap((p) => p.methods),
    columns,
    truncated: parts.some((p) => p.truncated),
    totalGroups: parts.reduce((n, p) => n + p.totalGroups, 0),
    ...counts,
    groups,
  };
}
const URGENCY: { severity: Severity; label: string; range: string }[] = [
  { severity: 'critical', label: 'Critical', range: 'below 40' },
  { severity: 'high', label: 'High', range: '40–59' },
  { severity: 'medium', label: 'Medium', range: '60–79' },
  { severity: 'low', label: 'Low', range: '80–94' },
];
const urgencyFor = (score: number): Severity => (score < 40 ? 'critical' : score < 60 ? 'high' : score < 80 ? 'medium' : 'low');
const money = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const PRIORITY_TEXT: Record<Finding['priority'], string> = {
  P1: 'Fix now',
  P2: 'Fix within a month',
  P3: 'Fix within 3 months',
  P4: 'Fix when you can',
};

function Section({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="mb-7">
      <h3 className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">
        {icon}
        {title}
      </h3>
      <div className="text-sm leading-relaxed text-ink">{children}</div>
    </section>
  );
}

function Stat({ label, icon, children, sub, info }: { label: string; icon: ReactNode; children: ReactNode; sub?: ReactNode; info?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-muted/40 p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ink-subtle">
        {icon}
        {label}
        {info && (
          <InfoTip size="md" label={`What “${label}” means`}>
            <span className="normal-case tracking-normal">{info}</span>
          </InfoTip>
        )}
      </p>
      <div className="mt-1">{children}</div>
      {sub && <p className="mt-1 text-xs text-ink-muted">{sub}</p>}
    </div>
  );
}

/** One rule per row: label on the left, exact detail on the right. */
function RuleTable({ rows }: { rows: { name: string; detail: ReactNode; strong?: boolean }[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <table className="w-full text-left text-sm">
        <tbody className="divide-y divide-line">
          {rows.map((r, i) => (
            <tr key={i} className={cx('align-top', r.strong && 'bg-brand-soft/40')}>
              <th scope="row" className="w-40 bg-muted/50 px-4 py-3 text-xs font-semibold text-ink-muted sm:w-48">{r.name}</th>
              <td className="px-4 py-3 text-sm leading-relaxed">{r.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Track the fix: status and notes (editors only). */
function TrackFix({ finding }: { finding: Finding }) {
  const update = useUpdateFinding(finding.assessmentId);
  const { notify } = useToast();
  const [status, setStatus] = useState<FindingStatus>(finding.status);
  const [notes, setNotes] = useState(finding.notes ?? '');
  useEffect(() => {
    setStatus(finding.status);
    setNotes(finding.notes ?? '');
    update.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finding.id]);
  const dirty = status !== finding.status || notes !== (finding.notes ?? '');
  return (
    <section className="rounded-xl border border-line p-4">
      <h3 className="mb-3 text-sm font-semibold">Track the fix</h3>
      <div className="space-y-3">
        <Field label="Where are you with this?">
          <Select<FindingStatus>
            label="Problem progress"
            value={status}
            onChange={setStatus}
            options={(Object.keys(FINDING_STATUS_LABEL) as FindingStatus[]).map((s) => ({ value: s, label: FINDING_STATUS_LABEL[s] }))}
          />
        </Field>
        <Field label="Notes" hint="Your team can see these notes.">
          <textarea className="input h-24 resize-y py-2" value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Priya is fixing this" />
        </Field>
        <InlineError error={update.error} />
        <Button
          variant="primary"
          icon={<Save className="h-4 w-4" />}
          disabled={!dirty || update.isPending}
          onClick={() => update.mutate({ id: finding.id, body: { status, notes } }, { onSuccess: () => notify('Saved', `Marked as ${FINDING_STATUS_LABEL[status]}.`, 'success') })}
        >
          {update.isPending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </section>
  );
}

/** A Check fields run as this card's per-field numbers: empty, duplicated or odd records per field. */
function checkScores(r: FieldCheckResult, kind: string): FieldScore[] {
  const row = (name: string, label: string, count: number, of: number): FieldScore => ({ field: name, label, count, of, pct: of ? Math.round((1000 * count) / of) / 10 : 0 });
  if (kind === 'missing') return r.fields.map((f) => row(f.name, f.label, f.empty, r.scanned));
  if (kind === 'duplicates')
    return r.fields.filter((f) => f.duplicates).map((f) => row(f.name, f.label, f.duplicates!.totalGroups + f.duplicates!.extraCopies, f.filled));
  if (kind === 'standardization')
    return r.fields.filter((f) => f.standardization).map((f) => row(f.name, f.label, f.standardization!.oddRecords, f.filled));
  return [];
}

/** The records: the measure's table (with the columns that prove why, duplicate groups) when there is one, else the problem's own list. */
function Records({
  area,
  indicator,
  finding,
  measureAssessmentId,
  legacy,
  initialObject,
  keyFields,
  fieldChoices = [],
  shownFields,
  checkData,
  flow,
}: {
  area: DiagnosticArea;
  indicator: IndicatorValue | null;
  finding: Finding | null;
  measureAssessmentId: string | null;
  legacy: boolean;
  initialObject?: string | null;
  /** Missing Key Fields: the key fields, so their empty cells are marked. */
  keyFields?: string[];
  /** Fields the records can be narrowed to (empty key fields, or fields with invalid data), with how many records. */
  fieldChoices?: { field: string; label: string; count: number }[];
  /** The fields ticked in Check fields on the page: only records with a problem in one of them. */
  shownFields?: string[] | null;
  /** The latest Check fields result: on a duplicates page, the ticked fields' groups replace the records table. */
  checkData?: FieldCheckResult | null;
  /** The steps from what was checked to the number, shown above the table (duplicates, missing key fields, invalid data). */
  flow?: FlowStep[] | null;
}) {
  const objects = indicator?.recordObjects ?? [];
  const preferred =
    (initialObject && objects.includes(initialObject) ? initialObject : null) ??
    (finding?.objectName && objects.includes(finding.objectName) ? finding.objectName : objects[0] ?? null);
  const [object, setObject] = useState<string | null>(preferred);
  useEffect(() => setObject(preferred), [preferred, indicator?.label, finding?.id]);
  // Excel-style column filters, for the records shown (start fresh for another object or measure).
  const [filters, setFilters] = useState<DataFilter[]>([]);
  useEffect(() => setFilters([]), [object, indicator?.label, finding?.id]);
  const useMeasure = !!object && !!measureAssessmentId && !!indicator;
  const choices = useMeasure ? fieldChoices : [];
  // Fields ticked in Check fields (null = all, the default). All ticked is the measure's own records; none ticked shows none.
  const every = choices.map((c) => c.field);
  const ticked = shownFields == null ? every : shownFields.filter((f) => every.includes(f));
  const only = ticked.length === every.length ? [] : ticked;
  const noneTicked = every.length > 0 && ticked.length === 0;
  // Duplicates: everything ticked (the default) shows the health check's groups; a pick shows those fields' groups
  // from Check fields, in this one table.
  const dupPicked = /duplicate/i.test(indicator?.label ?? finding?.name ?? '') && shownFields != null && checkData ? shownFields : null;
  const dupResult = dupPicked?.length ? mergeDuplicates(checkData!, dupPicked) : null;
  // No Activity: the period the table covers (undefined = the health check's 6 months; "90"; "since:YYYY-MM-DD").
  const noActivity = /^no activity/i.test(indicator?.label ?? '');
  const [period, setPeriod] = useState<string | undefined>();
  useEffect(() => setPeriod(undefined), [object, indicator?.label]);
  const measureRecords = useIndicatorRecords(useMeasure ? measureAssessmentId : null, area.id, indicator?.label ?? '', object, filters, only, period);
  const missing = /^missing/i.test(indicator?.label ?? '');
  // The flow follows what the person picked: the fields ticked in Check fields, and the table's column filters (its count).
  const standardization = /^data standardi/i.test(indicator?.label ?? '');
  const tableTotal = measureRecords.data?.pages[0]?.totalSize ?? null;
  const liveFlow =
    checkData && checkData.object === object && (missing || standardization)
      ? liveFlowFor(missing ? 'missing' : 'standardization', checkData, shownFields ?? null, tableTotal, filters.length > 0)
      : null;
  const findingRecords = useFindingRecords(finding?.id ?? null, !useMeasure && !!finding?.recordsAvailable, filters);
  const duplicates = /duplicate/i.test(indicator?.label ?? finding?.name ?? '');

  if (useMeasure) {
    return (
      <>
        {objects.length > 1 && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {objects.map((o) => (
              <button
                key={o}
                type="button"
                onClick={() => setObject(o)}
                className={cx('rounded-full border px-3 py-1 text-xs font-medium transition', o === object ? 'border-brand bg-brand-soft text-brand-ink' : 'border-line text-ink-muted hover:text-ink')}
              >
                {objectLabel(o)}
              </button>
            ))}
          </div>
        )}
        <div id="records-table" className="scroll-mt-20">
        {flow && !dupResult && (
          <div className="mb-3">
            {/* Nothing ticked in Check fields: the same steps, counting 0. */}
            <FlowSteps steps={noneTicked || dupPicked ? zeroFlow(liveFlow ?? flow) : liveFlow ?? flow} />
          </div>
        )}
        {dupPicked && !dupResult ? (
          <p className="rounded-xl border border-dashed border-line px-4 py-8 text-center text-sm text-ink-muted">
            No fields ticked. Tick a field in Check fields above, or <span className="font-medium">Select all</span>, to see its duplicates.
          </p>
        ) : dupResult ? (
          <div className="rounded-xl border border-line p-4">
            <h4 className="mb-3 text-sm font-semibold">Duplicates on {dupResult.rules.map((r) => r.join(' + ')).join(' · ')}</h4>
            <DuplicateResults
              result={dupResult}
              fileName={`duplicate-${object!.toLowerCase()}s.csv`}
              flag={dupPicked!.includes(ALL) ? null : dupPicked}
            />
          </div>
        ) : noneTicked ? (
          <p className="rounded-xl border border-dashed border-line px-4 py-8 text-center text-sm text-ink-muted">
            No fields ticked. Tick a field in Check fields above, or <span className="font-medium">Select all</span>, to see its records.
          </p>
        ) : (
        <>
        {duplicates && !checkData && (
          <p className="mb-3 rounded-lg border border-brand/20 bg-brand-soft/50 px-3 py-2 text-xs text-ink-muted">
            Showing every duplicate the health check found. To see the duplicates of one field, wait for <span className="font-medium text-ink">Check fields</span> above
            to finish reading the records (usually under a minute), then tick that field.
          </p>
        )}
        <RecordsTable
          query={measureRecords}
          title={only.length ? `${objectLabel(object!)} · ${only.map((f) => choices.find((c) => c.field === f)?.label ?? f).join(', ')}` : objectLabel(object!)}
          grouped={duplicates}
          csvUrl={indicatorApi.csvUrl(measureAssessmentId!, area.id, indicator!.label, object!, filters, only, period)}
          toolbar={noActivity ? <ActivityPeriod key={`${object}-${indicator!.label}`} onChange={setPeriod} /> : undefined}
          filters={filters}
          onFiltersChange={setFilters}
          keyFields={missing && only.length ? only : keyFields}
          markOnly={only}
          valuesSource={{
            key: ['indicator', measureAssessmentId, area.id, indicator!.label, object, only, period],
            load: (field, others, signal) => indicatorApi.values(measureAssessmentId!, area.id, indicator!.label, object!, field, others, signal, only, period),
          }}
        />
        </>
        )}
        </div>
        <p className="mt-2 text-[11px] text-ink-subtle">
          {object === 'Opportunity' && ['Duplicate', 'Missing', 'Data Standardi'].some((p) => indicator?.label.startsWith(p))
            ? 'Records are grouped by their Account (each shaded block is one Account). '
            : duplicates
              ? 'Each shaded block is one duplicate group (#group · records in it). '
              : ''}
          Read live from Salesforce with the connected user’s access. Click a name to open the record.
        </p>
      </>
    );
  }
  if (finding?.recordsAvailable) {
    return (
      <>
        <RecordsTable
          query={findingRecords}
          title="Affected records"
          csvUrl={findingApi.recordsCsvUrl(finding.id, filters)}
          filters={filters}
          onFiltersChange={setFilters}
          valuesSource={{ key: ['finding', finding.id], load: (field, others, signal) => findingApi.values(finding.id, field, others, signal) }}
        />
        <p className="mt-2 text-[11px] text-ink-subtle">Read live from Salesforce with the connected user’s access. Click a name to open the record.</p>
      </>
    );
  }
  if (finding?.sampleRecordsUrl) {
    return (
      <a href={finding.sampleRecordsUrl} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:underline">
        See the affected records in Salesforce <ExternalLink className="h-3.5 w-3.5" />
      </a>
    );
  }
  return (
    <p className="rounded-lg bg-muted/50 px-4 py-3 text-sm text-ink-muted">
      {legacy
        ? 'Check this area again to list the records behind this number.'
        : 'This is about settings or a summary across records, so there isn’t a list of records to show. The rules above say exactly what was inspected.'}
    </p>
  );
}

/**
 * The one details panel for a problem and the measure behind it: result and score, what we found and measure,
 * the exact rules as a table, the records, why it matters, how to fix it, and tracking.
 */
export function DetailsPanel({
  open,
  area,
  indicator,
  finding,
  measureAssessmentId,
  checkedAt,
  others = [],
  onClose,
  onOpenFinding,
  onCheckAgain,
  initialObject,
  asPage,
  extra,
  fieldCheck,
  onClearFieldCheck,
  shownFields,
  checkData,
}: {
  open: boolean;
  area: DiagnosticArea | undefined;
  indicator: IndicatorValue | null;
  finding: Finding | null;
  /** The health check that measured the area (may be earlier than the latest one). */
  measureAssessmentId: string | null;
  checkedAt?: string | null;
  /** Other open problems in this area, to jump to. */
  others?: Finding[];
  onClose: () => void;
  onOpenFinding?: (f: Finding) => void;
  onCheckAgain?: () => void;
  /** Object whose records to show first (e.g. the chip that was clicked). */
  initialObject?: string | null;
  /** Show as a full page instead of a side panel. */
  asPage?: boolean;
  /** Extra section after the records (e.g. the duplicate finder). */
  extra?: ReactNode;
  /** The latest Check fields run: the chart and its numbers follow the fields chosen there. */
  fieldCheck?: FieldCheckResult | null;
  onClearFieldCheck?: () => void;
  /** Fields ticked in Check fields on the page: the records show only those with a problem in one of them. */
  shownFields?: string[] | null;
  /** The latest Check fields result: on a duplicates page, the ticked fields' groups replace the records table. */
  checkData?: FieldCheckResult | null;
}) {
  const navigate = useNavigate();
  const { canEdit } = useRole();
  const v = indicator;
  const scored = v?.score != null;
  // After Check fields runs, the chart and its numbers show the fields chosen there instead of the check's own.
  const chartKind = v ? chartKindFor(v.label) : null;
  const fromCheck = fieldCheck && chartKind ? checkScores(fieldCheck, chartKind) : null;
  const shownScores = fromCheck?.length ? fromCheck : (v?.fieldScores ?? null);
  // Missing-field cards: how many key values are filled (what the score is based on), and how many records miss any.
  const empties = shownScores?.length && chartKind === 'missing' ? shownScores : null;
  const keyValues = empties
    ? (() => {
        const slots = empties.reduce((n, f) => n + f.of, 0);
        const empty = empties.reduce((n, f) => n + f.count, 0);
        return { slots, empty, filled: slots - empty, pct: slots ? (100 * (slots - empty)) / slots : 0 };
      })()
    : null;
  const recordsOf = empties?.[0]?.of ?? null;
  // The number in "Affected records", worked out from the Check fields run when it can be (else the health check's).
  const plural = fieldCheck ? objectLabel(fieldCheck.object) : '';
  const checkAffected: { n: number; text: string } | null = (() => {
    if (!fromCheck?.length || !fieldCheck) return null;
    if (chartKind === 'missing' && fieldCheck.anyEmpty != null) {
      const worst = [...fromCheck].sort((a, b) => b.count - a.count).filter((f) => f.count).slice(0, 4);
      return {
        n: fieldCheck.anyEmpty,
        text:
          `${fmtNumber(fieldCheck.anyEmpty)} of ${fmtNumber(fieldCheck.scanned)} ${plural} miss at least one of the ${fromCheck.length} fields you checked.` +
          (worst.length ? ` Most often empty: ${worst.map((f) => `${f.label} (${Math.round(f.pct)}% empty)`).join(', ')}.` : ''),
      };
    }
    if (chartKind === 'duplicates') {
      const dup = fieldCheck.combined ?? (fieldCheck.fields.length === 1 ? fieldCheck.fields[0].duplicates : null);
      if (!dup) return null;
      return {
        n: dup.extraCopies,
        text: `${fmtNumber(dup.extraCopies)} extra ${plural} (${fmtNumber(dup.totalGroups)} groups) match another record on ${dup.rules[0]?.join(' + ')}, out of ${fmtNumber(dup.scanned)} read.`,
      };
    }
    return null;
  })();
  const missingAny = fromCheck?.length
    ? (fieldCheck?.anyEmpty ?? null)
    : (finding?.affectedRecords ?? (v && /^missing/i.test(v.label) && v.unit === '%' && recordsOf ? Math.round((v.value * recordsOf) / 100) : null));
  const legacy = !!v && !v.how && !v.rule && !(v.criteria ?? []).length;
  // Some checks raise a problem whenever any record is affected (their rule says so), whatever the score.
  const raisesOnAny = /problem is raised whenever any/i.test(v?.rule ?? '');
  // The score below which a problem is raised: what the card's rule says (e.g. "below 90"), else 95.
  const raiseBelow = Number(v?.rule?.match(/problem is raised when the score is below (\d+)/i)?.[1]) || (chartKind === 'missing' ? 90 : PROBLEM_BELOW);
  const urgency = scored && (raisesOnAny ? v!.value > 0 : v!.score! < raiseBelow) ? URGENCY.find((u) => u.severity === urgencyFor(v!.score!))! : null;
  const rangeOf = (u: (typeof URGENCY)[number]) => (u.severity !== 'low' ? u.range : raisesOnAny ? '80 or more' : `80–${raiseBelow - 1}`);
  // The (i) beside Score: this page's own numbers worked through, then the rule and the urgency bands.
  const scoreInfo = v && scored ? (
    <span className="block space-y-1.5">
      {keyValues && recordsOf != null && !fromCheck?.length ? (
        <span className="block">
          {fmtNumber(recordsOf)} records × {empties!.length} key fields = {fmtNumber(keyValues.slots)} values. {fmtNumber(keyValues.empty)} are empty, so{' '}
          {fmtNumber(keyValues.filled)} are filled = <b>{Math.round(keyValues.pct)}%</b>. Score = 100 × ({Math.round(keyValues.pct)} − 50) ÷ (95 − 50) ={' '}
          {Math.round((100 * (keyValues.pct - 50)) / 45)}
          {keyValues.pct < 50 ? ' → 0 (can’t go below 0)' : keyValues.pct > 95 ? ' → 100' : ''}.
        </span>
      ) : (
        <span className="block">
          Result <b>{fmtNumber(v.value)}{v.unit === '%' ? '%' : ''}</b> → score <b>{Math.round(v.score!)}</b>.{v.how ? ` ${v.how}` : ''}
        </span>
      )}
      {v.rule && <span className="block">Rule: {v.rule}</span>}
      <span className="block">
        {raisesOnAny
          ? 'Urgency: below 40 Critical (P1) · 40–59 High (P2) · 60–79 Medium (P3) · 80 or more Low (P4). A problem is raised whenever any record is affected.'
          : `Urgency: below 40 Critical (P1) · 40–59 High (P2) · 60–79 Medium (P3) · 80–${raiseBelow - 1} Low (P4) · ${raiseBelow} or more: no problem raised.`}
      </span>
    </span>
  ) : undefined;
  const title = finding?.name ?? v?.label ?? '';
  // The steps from what was checked to the number, for Area 1 cards: in its own section, or for duplicates, missing key
  // fields and data standardization right above their records table (which it explains)
  const allFlow = v ? flowFor(v, finding) : null;
  const fieldFlow = v?.fieldList ? fieldFlowFor(v) : null; // area 2: from the fields looked at to the ones listed, above the list
  const flowAtRecords = !!v && /^(duplicate|missing|data standardi)/i.test(v.label);
  const flow = flowAtRecords ? null : allFlow;
  // A measure can cover several objects (e.g. phone numbers on Accounts, Contacts and Leads) while a problem is about one.
  const measureObjects = v?.recordObjects ?? [];
  const wide = !!finding?.objectName && measureObjects.length > 1;

  const ruleRows = v
    ? [
        ...(v.criteria ?? []).map(([name, detail]) => ({ name, detail: detail as ReactNode })),
        ...(v.rule ? [{ name: 'Score', detail: v.rule as ReactNode }] : []),
        // Cards shown for information (All Fields) never raise a problem: no urgency rule for them.
        ...(v.score == null ? [] : [{
          name: 'Problem raised when',
          detail: (
            <>
              {raisesOnAny ? <>Any record is affected (the score sets the urgency).</> : <>The score is below <strong>{raiseBelow}</strong>.</>} Urgency:{' '}
              {URGENCY.map((u, i) => (
                <span key={u.severity} className="whitespace-nowrap">
                  <span className="font-medium" style={{ color: SEVERITY_COLORS[u.severity] }}>{u.label}</span> {rangeOf(u)}
                  {i < URGENCY.length - 1 ? ' · ' : ''}
                </span>
              ))}
            </>
          ),
        }]),
        {
          name: 'This org',
          strong: true,
          detail: scored ? (
            <>
              Result <strong>{fmtNumber(v.value)}{v.unit === '%' ? '%' : ''}</strong>, score <strong>{Math.round(v.score!)}</strong> →{' '}
              {urgency ? <span className="font-semibold" style={{ color: SEVERITY_COLORS[urgency.severity] }}>{urgency.label}</span> : <span className="font-semibold text-good">no problem raised</span>}
              {wide && finding && (
                <>
                  {' '}across {measureObjects.map((o) => objectLabel(o)).join(', ')}. Each object is also checked on its own:{' '}
                  {objectLabel(finding.objectName!)} → <span className="font-semibold" style={{ color: SEVERITY_COLORS[finding.severity] }}>{finding.severity}</span> ({fmtNumber(finding.affectedRecords)} records).
                </>
              )}
            </>
          ) : (
            <>
              Result <strong>{fmtNumber(v.value)}{v.unit === '%' ? '%' : ''}</strong> — {legacy ? 'scored in an older health check' : 'shown for information; it doesn’t change the area score'}
            </>
          ),
        },
      ]
    : [];
  const list = others.filter((f) => f.id !== finding?.id).slice(0, 6);

  const subtitle = (
    <div className="flex flex-wrap items-center gap-2">
      {area && <span className="text-xs text-ink-subtle">Area {area.number}: {area.name}{checkedAt ? ` · checked ${fmtDate(checkedAt)}` : ''}</span>}
      {finding && <SeverityBadge severity={finding.severity} />}
      {finding && <FindingStatusBadge status={finding.status} />}
      {finding && <ChangeBadge finding={finding} />}
      {finding && v && v.label !== finding.name && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-ink-muted">Measured by: {v.label}</span>}
    </div>
  );
  const areaPath = area ? `/assessment/${area.categoryId}/${area.id}` : null;

  const body = (
    <>
      {(v || finding) && area && (
        <>
          {/* the numbers */}
          <div className={cx('mb-6 grid gap-3', finding && v ? 'sm:grid-cols-3' : 'sm:grid-cols-2')}>
            {finding ? (
              <Stat
                label="Affected records"
                icon={<Users className="h-3.5 w-3.5" />}
                info={checkAffected?.text ?? finding.description}
                sub={
                  checkAffected
                    ? `From the fields you checked · health check: ${fmtNumber(finding.affectedRecords)}`
                    : finding.previousAffected != null
                      ? `${fmtNumber(finding.previousAffected)} last check`
                      : 'New since the last check'
                }
              >
                <p className={cx('text-3xl font-semibold tabular-nums tracking-tight', checkAffected && 'text-brand')}>
                  {fmtNumber(checkAffected?.n ?? finding.affectedRecords)}
                </p>
              </Stat>
            ) : (
              v && (
                <Stat
                  label="Result"
                  icon={<Target className="h-3.5 w-3.5" />}
                  info={checkAffected ? `${checkAffected.text} (The result below is the health check’s.)` : (v.how ?? undefined)}
                  sub={v.direction === 'higher-better' ? 'Higher is better' : 'Lower is better'}
                >
                  <p className="text-3xl font-semibold tabular-nums tracking-tight">
                    {fmtNumber(v.value)}
                    {v.unit === '%' && <span className="text-lg text-ink-subtle">%</span>}
                  </p>
                </Stat>
              )
            )}
            {v && (
              <Stat
                label={finding && wide ? `Score · ${v.label}` : 'Score'}
                icon={<AlertTriangle className="h-3.5 w-3.5" />}
                info={scoreInfo}
                sub={
                  scored ? (
                    <>
                      <span className="font-semibold" style={{ color: urgency ? SEVERITY_COLORS[urgency.severity] : 'rgb(var(--good))' }}>
                        {urgency ? `${urgency.label} (score ${rangeOf(urgency)})` : raisesOnAny ? 'No problem raised (no records affected)' : `No problem raised (${raiseBelow} or more)`}
                      </span>
                      {finding && wide && (
                        <span className="mt-1 block">
                          Across {measureObjects.map((o) => objectLabel(o)).join(', ')}. On {objectLabel(finding.objectName!)} alone this problem is{' '}
                          <span className="font-semibold" style={{ color: SEVERITY_COLORS[finding.severity] }}>{finding.severity}</span>.
                        </span>
                      )}
                    </>
                  ) : (
                    'For information — not scored'
                  )
                }
              >
                {scored ? (
                  <>
                    <p className="text-3xl font-semibold tabular-nums tracking-tight" style={{ color: urgency ? SEVERITY_COLORS[urgency.severity] : 'rgb(var(--good))' }}>
                      {Math.round(v.score!)}
                      <span className="text-lg font-medium text-ink-subtle"> / 100</span>
                    </p>
                    <div className="relative mt-2 h-2 rounded-full bg-gradient-to-r from-[#dc2626] via-[#f59e0b] to-[#16a34a]">
                      <span
                        className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-surface shadow"
                        style={{ left: `${Math.max(0, Math.min(100, v.score!))}%`, background: urgency ? SEVERITY_COLORS[urgency.severity] : 'rgb(var(--good))' }}
                      />
                    </div>
                    {keyValues && !fromCheck?.length && (
                      <p className="mt-2 text-xs text-ink-muted" title="The score follows this: 100 at 95% filled or more, 0 at 50% or less">
                        Based on <span className="font-semibold text-ink">{Math.round(keyValues.pct)}% of key values filled</span> ({fmtNumber(keyValues.filled)} of{' '}
                        {fmtNumber(keyValues.slots)})
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-3xl font-semibold text-ink-subtle">—</p>
                )}
              </Stat>
            )}
            {finding &&
              (finding.valueAtRisk ? (
                <Stat label="Value at risk" icon={<CircleDollarSign className="h-3.5 w-3.5" />} sub="Total Amount involved">
                  <p className="text-3xl font-semibold tabular-nums tracking-tight">{money.format(finding.valueAtRisk)}</p>
                </Stat>
              ) : (
                <Stat label="Suggested priority" icon={<Flag className="h-3.5 w-3.5" />} sub={PRIORITY_TEXT[finding.priority]}>
                  <p className="text-3xl font-semibold tracking-tight">{finding.priority}</p>
                </Stat>
              ))}
          </div>

          {fromCheck?.length ? (
            <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-brand/30 bg-brand-soft/50 px-3 py-2 text-xs text-brand-ink">
              <span className="min-w-0 flex-1">
                Showing the <span className="font-semibold">{fromCheck.length} fields you checked</span> below ({fmtNumber(fieldCheck!.scanned)}{' '}
                {objectLabel(fieldCheck!.object).toLowerCase()} read{fieldCheck!.truncated ? ', the first 20,000' : ''}). The score above is still the health check’s.
              </span>
              <button type="button" onClick={onClearFieldCheck} className="font-semibold text-brand hover:underline">
                Back to this check’s fields
              </button>
            </div>
          ) : null}
          {shownScores?.length && chartKind ? <FieldScoreChart scores={shownScores} kind={chartKind} /> : null}
          {keyValues && empties && (
            <div className="-mt-4 mb-6 rounded-lg border border-line bg-muted/40 px-4 py-3 text-xs leading-relaxed text-ink-muted">
              {missingAny != null && recordsOf != null && (
                <p>
                  <span className="font-semibold text-ink">{fmtNumber(missingAny)}</span> of {fmtNumber(recordsOf)} records miss at least one of these{' '}
                  {empties.length} fields. A record missing several counts once, so the rows add up to more ({fmtNumber(keyValues.empty)}).
                </p>
              )}
              <p className={missingAny != null ? 'mt-1' : ''}>
                {fmtNumber(recordsOf ?? 0)} records × {empties.length} fields = {fmtNumber(keyValues.slots)} values that should be filled;{' '}
                {fmtNumber(keyValues.empty)} are empty, so <span className="font-semibold text-ink">{Math.round(keyValues.pct)}% are filled</span> — that’s what the
                score is based on (100 at 95% or more, 0 at 50% or less).
              </p>
            </div>
          )}

          {legacy && (
            <div className="mb-6 flex flex-wrap items-center gap-3 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn">
              <Info className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1">This result is from a health check run before the rules were recorded. Check this area again to see the exact rules and the records behind the number.</span>
              {onCheckAgain && (
                <button type="button" onClick={onCheckAgain} className="rounded-md bg-warn px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110">
                  Check this area again
                </button>
              )}
            </div>
          )}

          {finding && (
            <Section icon={<Target className="h-3.5 w-3.5" />} title="What we found">
              <p>{finding.description}</p>
            </Section>
          )}
          {v && (v.how || !finding) && (
            <Section icon={<Search className="h-3.5 w-3.5" />} title="What we measure">
              <p>{v.how ?? area.description}</p>
            </Section>
          )}
          {v && flow && (
            <Section icon={<ListOrdered className="h-3.5 w-3.5" />} title="How the number is reached">
              <FlowSteps steps={flow} />
            </Section>
          )}

          {v && (
            <Section icon={<ListChecks className="h-3.5 w-3.5" />} title="How it’s flagged — the exact rules">
              <RuleTable rows={ruleRows} />
            </Section>
          )}

          {extra}

          {v?.fieldList ? (
            <Section icon={<Database className="h-3.5 w-3.5" />} title="The fields behind this number">
              <FieldsBehind indicator={v} object={initialObject ?? objectOfFieldCard(v.label)} flow={fieldFlow} />
            </Section>
          ) : (
            <Section icon={<Database className="h-3.5 w-3.5" />} title={finding ? 'The records' : 'The records behind this number'}>
              <Records area={area} indicator={v} finding={finding} measureAssessmentId={measureAssessmentId} legacy={legacy} initialObject={initialObject}
                keyFields={empties?.map((f) => f.field)}
                fieldChoices={(chartKind === 'missing' ? shownScores : chartKind === 'standardization' ? v?.fieldScores : null)?.map((f) => ({ field: f.field, label: f.label, count: f.count })) ?? []}
                shownFields={shownFields} checkData={checkData} flow={flowAtRecords ? allFlow : null} />
            </Section>
          )}

          {finding && (
            <>
              <Section icon={<Lightbulb className="h-3.5 w-3.5" />} title="Why it matters">
                <p>{finding.whyItMatters}</p>
              </Section>
              <Section icon={<TrendingDown className="h-3.5 w-3.5" />} title="Business impact">
                <p>{finding.businessImpact}</p>
              </Section>
              <Section icon={<Wrench className="h-3.5 w-3.5" />} title="How to fix it">
                <div className="rounded-lg border border-brand/20 bg-brand-soft p-3 text-brand-ink">{finding.recommendedAction}</div>
                {finding.fixUrl && (
                  <a
                    href={finding.fixUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-2 inline-flex h-9 items-center gap-2 rounded-lg bg-brand px-4 text-sm font-medium text-white shadow-sm transition hover:brightness-110"
                  >
                    <Wrench className="h-4 w-4" /> Fix it in Salesforce <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
                <FixPlanPanel findingId={finding.id} />
                <p className="mt-3 text-xs text-ink-muted">
                  <span className="font-semibold text-ink">{finding.priority}</span> — {PRIORITY_TEXT[finding.priority]} · detected {fmtDateTime(finding.detectedAt)}
                </p>
              </Section>
              {canEdit && <TrackFix finding={finding} />}
            </>
          )}

          {list.length > 0 && onOpenFinding && (
            <div className="mt-7">
              <Section icon={<AlertTriangle className="h-3.5 w-3.5" />} title={finding ? 'Other problems in this area' : 'Problems raised in this area'}>
                <ul className="space-y-1">
                  {list.map((f) => (
                    <li key={f.id}>
                      <button type="button" onClick={() => onOpenFinding(f)} className="group flex w-full items-center gap-2 rounded-lg border border-line px-3 py-2 text-left text-sm transition hover:border-brand/40 hover:bg-brand-soft/40">
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: SEVERITY_COLORS[f.severity] }} />
                        <span className="min-w-0 flex-1 truncate group-hover:text-brand">{f.name}</span>
                        {f.affectedRecords > 0 && <span className="text-xs tabular-nums text-ink-subtle">{fmtNumber(f.affectedRecords)}</span>}
                        <ArrowRight className="h-3.5 w-3.5 text-ink-subtle group-hover:text-brand" />
                      </button>
                    </li>
                  ))}
                </ul>
              </Section>
            </div>
          )}
        </>
      )}
    </>
  );

  if (asPage) {
    return (
      <div>
        <button type="button" onClick={onClose} className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
          <ArrowLeft className="h-4 w-4" /> Back
        </button>
        <section className="card mb-6 p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
              <div className="mt-2">{subtitle}</div>
            </div>
            {areaPath && (
              <Button className="shrink-0" onClick={() => navigate(areaPath)}>
                Open this area
              </Button>
            )}
          </div>
        </section>
        <div className="card p-6">{body}</div>
      </div>
    );
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={title}
      subtitle={subtitle}
      footer={
        areaPath && (
          <Button
            onClick={() => {
              onClose();
              navigate(areaPath);
            }}
          >
            Open this area
          </Button>
        )
      }
    >
      {body}
    </Drawer>
  );
}

/** Which measure raised a problem: the saved link, or (older checks) a measure with the same name. */
export function measureFor(finding: Finding, indicators: IndicatorValue[]): IndicatorValue | null {
  return indicators.find((i) => i.label === finding.measure) ?? indicators.find((i) => i.label === finding.name) ?? null;
}

/** Problems a measure raised (saved link, or same name for older checks). */
export function findingsFor(indicator: IndicatorValue, findings: Finding[]): Finding[] {
  const linked = findings.filter((f) => f.measure === indicator.label);
  return linked.length ? linked : findings.filter((f) => !f.measure && f.name === indicator.label);
}
