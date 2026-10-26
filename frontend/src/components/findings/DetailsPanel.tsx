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
  Save,
  Search,
  Target,
  TrendingDown,
  Users,
  Wrench,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { findingApi, indicatorApi } from '@/api/endpoints';
import { useFindingRecords, useIndicatorRecords, useRole, useUpdateFinding } from '@/api/queries';
import { SEVERITY_COLORS } from '@/components/charts/Charts';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDate, fmtDateTime, fmtNumber } from '@/lib/format';
import type { DataFilter, DiagnosticArea, Finding, FindingStatus, IndicatorValue, Severity } from '@/types';
import { FINDING_STATUS_LABEL, FindingStatusBadge, SeverityBadge } from '../ui/Badges';
import { Button } from '../ui/Button';
import { Field, Select } from '../ui/Form';
import { Drawer } from '../ui/Overlay';
import { InlineError } from '../ui/States';
import { ChangeBadge } from './AffectedRecords';
import { FixPlanPanel } from './FixPlanPanel';
import { RecordsTable } from './RecordsTable';
import { FieldListTable } from './FieldListTable';
import { FieldScoreChart, chartKindFor } from './FieldScoreChart';

/** Same thresholds the engine uses (backend/app/engine/core.py → severity_for, finding min_score). */
const PROBLEM_BELOW = 95;
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

function Stat({ label, icon, children, sub }: { label: string; icon: ReactNode; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-muted/40 p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ink-subtle">
        {icon}
        {label}
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

/** The records: the measure's table (with the columns that prove why, duplicate groups) when there is one, else the problem's own list. */
function Records({
  area,
  indicator,
  finding,
  measureAssessmentId,
  legacy,
  initialObject,
}: {
  area: DiagnosticArea;
  indicator: IndicatorValue | null;
  finding: Finding | null;
  measureAssessmentId: string | null;
  legacy: boolean;
  initialObject?: string | null;
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
  const measureRecords = useIndicatorRecords(useMeasure ? measureAssessmentId : null, area.id, indicator?.label ?? '', object, filters);
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
        <RecordsTable
          query={measureRecords}
          title={objectLabel(object!)}
          grouped={duplicates}
          csvUrl={indicatorApi.csvUrl(measureAssessmentId!, area.id, indicator!.label, object!, filters)}
          filters={filters}
          onFiltersChange={setFilters}
          valuesSource={{
            key: ['indicator', measureAssessmentId, area.id, indicator!.label, object],
            load: (field, others, signal) => indicatorApi.values(measureAssessmentId!, area.id, indicator!.label, object!, field, others, signal),
          }}
        />
        <p className="mt-2 text-[11px] text-ink-subtle">
          {duplicates ? 'Each shaded block is one duplicate group (#group · records in it). ' : ''}
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
}) {
  const navigate = useNavigate();
  const { canEdit } = useRole();
  const v = indicator;
  const scored = v?.score != null;
  const legacy = !!v && !v.how && !v.rule && !(v.criteria ?? []).length;
  const urgency = scored && v!.score! < PROBLEM_BELOW ? URGENCY.find((u) => u.severity === urgencyFor(v!.score!))! : null;
  const title = finding?.name ?? v?.label ?? '';
  // A measure can cover several objects (e.g. phone numbers on Accounts, Contacts and Leads) while a problem is about one.
  const measureObjects = v?.recordObjects ?? [];
  const wide = !!finding?.objectName && measureObjects.length > 1;

  const ruleRows = v
    ? [
        ...(v.criteria ?? []).map(([name, detail]) => ({ name, detail: detail as ReactNode })),
        ...(v.rule ? [{ name: 'Score', detail: v.rule as ReactNode }] : []),
        {
          name: 'Problem raised when',
          detail: (
            <>
              The score is below <strong>{PROBLEM_BELOW}</strong>. Urgency:{' '}
              {URGENCY.map((u, i) => (
                <span key={u.severity} className="whitespace-nowrap">
                  <span className="font-medium" style={{ color: SEVERITY_COLORS[u.severity] }}>{u.label}</span> {u.range}
                  {i < URGENCY.length - 1 ? ' · ' : ''}
                </span>
              ))}
            </>
          ),
        },
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
              <Stat label="Affected records" icon={<Users className="h-3.5 w-3.5" />} sub={finding.previousAffected != null ? `${fmtNumber(finding.previousAffected)} last check` : 'New since the last check'}>
                <p className="text-3xl font-semibold tabular-nums tracking-tight">{fmtNumber(finding.affectedRecords)}</p>
              </Stat>
            ) : (
              v && (
                <Stat label="Result" icon={<Target className="h-3.5 w-3.5" />} sub={v.direction === 'higher-better' ? 'Higher is better' : 'Lower is better'}>
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
                sub={
                  scored ? (
                    <>
                      <span className="font-semibold" style={{ color: urgency ? SEVERITY_COLORS[urgency.severity] : 'rgb(var(--good))' }}>
                        {urgency ? `${urgency.label} (score ${urgency.range})` : `No problem raised (${PROBLEM_BELOW} or more)`}
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

          {v?.fieldScores?.length && chartKindFor(v.label) ? <FieldScoreChart scores={v.fieldScores} kind={chartKindFor(v.label)!} /> : null}

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

          {v && (
            <Section icon={<ListChecks className="h-3.5 w-3.5" />} title="How it’s flagged — the exact rules">
              <RuleTable rows={ruleRows} />
            </Section>
          )}

          {extra}

          {v?.fieldList ? (
            <Section icon={<Database className="h-3.5 w-3.5" />} title="The fields behind this number">
              <FieldListTable items={v.fieldList} />
            </Section>
          ) : (
            <Section icon={<Database className="h-3.5 w-3.5" />} title={finding ? 'The records' : 'The records behind this number'}>
              <Records area={area} indicator={v} finding={finding} measureAssessmentId={measureAssessmentId} legacy={legacy} initialObject={initialObject} />
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
