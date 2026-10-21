import { motion } from 'framer-motion';
import { ArrowRight, CalendarDays, TriangleAlert } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { SEVERITY_COLORS } from '@/components/charts/Charts';
import { SEVERITY_RANK } from '@/lib/health';
import { getAreaRelease } from '@/config/categories';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { AreaResult, DiagnosticArea, Finding, ObjectResult } from '@/types';
import { Badge, ReleaseBadge } from '../ui/Badges';
import { Button } from '../ui/Button';
import { InfoTip } from '../ui/HelpTip';
import { ScoreRing } from '../ui/Visuals';
import type { IndicatorValue } from '@/types';

/** Rough health of one number, for the coloured dot only (the area score is the real measure). */
function indicatorTone(i: IndicatorValue): 'good' | 'warn' | 'bad' {
  if (i.unit === '%') {
    const good = i.direction === 'higher-better' ? i.value : 100 - i.value;
    return good >= 90 ? 'good' : good >= 70 ? 'warn' : 'bad';
  }
  if (i.direction === 'lower-better') return i.value === 0 ? 'good' : i.value <= 10 ? 'warn' : 'bad';
  return i.value > 0 ? 'good' : 'warn';
}

const DOT = { good: 'bg-good', warn: 'bg-warn', bad: 'bg-bad' };

export function DiagnosticAreaCard({
  area,
  color,
  result,
  findingsCount,
  lastAssessed,
  findings = [],
  objects = [],
  assessmentId,
  onSelectFinding,
  onSelectObject,
  onSelectMeasure,
}: {
  area: DiagnosticArea;
  color: string;
  result: AreaResult | undefined;
  findingsCount: number;
  lastAssessed: string | null;
  /** This area's problems; the most urgent open ones are listed on the card. */
  findings?: Finding[];
  /** Per-object results (Data Quality); the card shows the number that belongs to this area. */
  objects?: ObjectResult[];
  assessmentId?: string;
  /** Open a problem in place (side panel) instead of going to My Results. */
  onSelectFinding?: (f: Finding) => void;
  /** Open one object's problems in this area in place. */
  onSelectObject?: (o: ObjectChip) => void;
  /** Open one of the measures shown on the card. */
  onSelectMeasure?: (label: string) => void;
}) {
  const navigate = useNavigate();
  const release = getAreaRelease(area);
  const assessed = result?.status === 'assessed';

  return (
    <motion.article
      layout
      whileHover={{ y: -3 }}
      transition={{ type: 'spring', stiffness: 380, damping: 28 }}
      className="card group relative flex h-full flex-col overflow-hidden p-5 transition-shadow hover:shadow-pop"
    >
      <span className="pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full opacity-0 blur-2xl transition-opacity duration-500 group-hover:opacity-25" style={{ background: color }} />
      <span className="absolute inset-x-0 top-0 h-0.5 origin-left scale-x-0 transition-transform duration-500 group-hover:scale-x-100" style={{ background: color }} />
      <div className="flex items-start gap-4">
        <span className="flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-lg text-white shadow-sm" style={{ background: color }}>
          <span className="text-[9px] font-semibold uppercase leading-none opacity-80">Area</span>
          <span className="text-base font-bold leading-none">{area.number}</span>
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="min-h-[4.125em] text-[15px] font-semibold leading-snug">
            {area.name}{' '}
            <InfoTip label={`About area ${area.number}`}>{area.description}</InfoTip>
          </h3>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <ReleaseBadge release={release} />
            {result && (
              <Badge tone={assessed ? 'good' : result.status === 'failed' ? 'bad' : 'neutral'}>
                {assessed ? 'Checked' : result.status === 'failed' ? 'Check failed' : 'Skipped'}
              </Badge>
            )}
          </div>
        </div>
      </div>

      {assessed && result.score !== null ? (
        <div className="mt-4 flex items-center gap-4">
          <ScoreRing score={result.score} size={72} stroke={7} showBand={false} />
          <ul className="min-w-0 flex-1 space-y-1.5">
            {result.indicators.filter((i) => area.indicators.includes(i.label)).slice(0, 3).map((i) => (
              <li key={i.label}>
                <button
                  type="button"
                  disabled={!onSelectMeasure}
                  onClick={() => onSelectMeasure?.(i.label)}
                  className="group/m -mx-1.5 flex w-[calc(100%+0.75rem)] items-center gap-2 rounded-md px-1.5 py-0.5 text-left text-xs enabled:hover:bg-muted"
                  title={onSelectMeasure ? 'See the rules and the records behind this number' : undefined}
                >
                  <span className={cx('h-1.5 w-1.5 shrink-0 rounded-full', DOT[indicatorTone(i)])} />
                  <span className="min-w-0 flex-1 truncate text-ink-muted group-enabled/m:group-hover/m:text-brand" title={i.label}>{i.label}</span>
                  <span className="font-semibold tabular-nums">
                    {fmtNumber(Math.round(i.value))}
                    {i.unit === '%' && '%'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-dashed border-line px-3 py-2 text-xs text-ink-subtle">
          {release === 'coming-soon'
            ? 'This area can be checked in a later release.'
            : result?.message ?? 'Not checked yet — include it in your next health check.'}
        </div>
      )}

      {assessed && assessmentId && <AreaExtras areaId={area.id} findings={findings} objects={objects} assessmentId={assessmentId} onSelectFinding={onSelectFinding} onSelectObject={onSelectObject} />}

      <div className="flex-1" />

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1">
          <TriangleAlert className="h-3.5 w-3.5" />
          {assessed ? `${findingsCount} problem${findingsCount === 1 ? '' : 's'}` : 'No problems'}
        </span>
        <span className="inline-flex items-center gap-1">
          <CalendarDays className="h-3.5 w-3.5" />
          {assessed && (result?.checkedAt ?? lastAssessed) ? `Last checked ${fmtDate((result?.checkedAt ?? lastAssessed)!)}` : 'Not checked yet'}
        </span>
      </div>

      <Button
        className="mt-4 w-full"
        size="sm"
        variant={assessed ? 'subtle' : 'secondary'}
        onClick={() => navigate(`/assessment/${area.categoryId}/${area.id}`)}
        iconRight={<ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />}
      >
        See details
      </Button>
    </motion.article>
  );
}

/** What each Data Quality area measures per object. */
const OBJECT_METRIC: Record<string, (o: ObjectResult) => { text: string; tone: 'good' | 'warn' | 'bad'; measure: string } | null> = {
  'area-1': (o) => (o.duplicates === null ? null : { text: o.duplicates ? `${fmtNumber(o.duplicates)} duplicates` : 'No duplicates', tone: o.duplicates ? (o.duplicates > 10 ? 'bad' : 'warn') : 'good', measure: `Duplicate ${o.label}` }),
  'area-2': (o) => (o.completeness === null ? null : { text: `${Math.round(o.completeness)}% filled in`, tone: o.completeness >= 90 ? 'good' : o.completeness >= 70 ? 'warn' : 'bad', measure: 'Field completeness' }),
};

/** One object in an area's "By object" list. */
export interface ObjectChip {
  name: string;
  label: string;
  text: string;
  tone: 'good' | 'warn' | 'bad';
  /** The measure this chip's number comes from (Data Quality), if any. */
  measure?: string;
}

/** Plain names for Salesforce objects that aren't in the per-object results. */
const OBJECT_LABELS: Record<string, string> = {
  Account: 'Accounts', Contact: 'Contacts', Lead: 'Leads', Opportunity: 'Opportunities', Case: 'Cases', Task: 'Tasks', Event: 'Events',
  Campaign: 'Campaigns', Contract: 'Contracts', Order: 'Orders', Quote: 'Quotes', QuoteLineItem: 'Quote lines', User: 'Users',
  Product2: 'Products', Pricebook2: 'Price books', PricebookEntry: 'Price book entries', OpportunityLineItem: 'Opportunity products',
  Report: 'Reports', Dashboard: 'Dashboards', Flow: 'Flows', ApexTrigger: 'Apex triggers', ApexClass: 'Apex classes',
  PermissionSet: 'Permission sets', Profile: 'Profiles', ContentVersion: 'Files', EmailTemplate: 'Email templates',
};

export function objectLabel(name: string, known?: string) {
  return known ?? OBJECT_LABELS[name] ?? name.replace(/__c$/, '').replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2');
}

const OPEN = (f: Finding) => f.status !== 'resolved' && f.status !== 'accepted-risk';

/** Data Quality areas use their measured numbers; every other area groups its open problems by object. */
function objectChips(areaId: string, findings: Finding[], objects: ObjectResult[]): ObjectChip[] {
  const metric = OBJECT_METRIC[areaId];
  if (metric) {
    return objects.flatMap((o) => {
      const m = metric(o);
      return m ? [{ name: o.name, label: o.label, ...m }] : [];
    });
  }
  const labels = new Map(objects.map((o) => [o.name, o.label]));
  const groups = new Map<string, Finding[]>();
  for (const f of findings.filter(OPEN)) {
    if (f.objectName) groups.set(f.objectName, [...(groups.get(f.objectName) ?? []), f]);
  }
  return [...groups.entries()]
    .map(([name, fs]) => {
      const worst = Math.max(...fs.map((f) => SEVERITY_RANK[f.severity]));
      return {
        name,
        label: objectLabel(name, labels.get(name)),
        text: `${fs.length} problem${fs.length === 1 ? '' : 's'}`,
        tone: (worst >= SEVERITY_RANK.high ? 'bad' : worst >= SEVERITY_RANK.medium ? 'warn' : 'good') as ObjectChip['tone'],
        n: fs.length,
      };
    })
    .sort((a, b) => b.n - a.n)
    .map(({ n: _n, ...c }) => c);
}

function AreaExtras({
  areaId,
  findings,
  objects,
  assessmentId,
  onSelectFinding,
  onSelectObject,
}: {
  areaId: string;
  findings: Finding[];
  objects: ObjectResult[];
  assessmentId: string;
  onSelectFinding?: (f: Finding) => void;
  onSelectObject?: (o: ObjectChip) => void;
}) {
  const top = findings
    .filter((f) => f.status !== 'resolved' && f.status !== 'accepted-risk')
    .sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords)
    .slice(0, 3);
  const perObject = objectChips(areaId, findings, objects);
  const base = `/results?assessment=${encodeURIComponent(assessmentId)}`;
  if (!top.length && !perObject.length) return null;

  return (
    <div className="mt-4 space-y-3 border-t border-line pt-3">
      {top.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">Fix first</p>
          <ul>
            {top.map((f) => {
              const row = (
                <>
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: SEVERITY_COLORS[f.severity] }} title={f.severity} />
                  <span className="min-w-0 flex-1 truncate group-hover/row:text-brand">{f.name}</span>
                  {f.affectedRecords > 0 && <span className="shrink-0 tabular-nums text-ink-subtle">{fmtNumber(f.affectedRecords)}</span>}
                </>
              );
              const cls = 'group/row -mx-2 flex w-[calc(100%+1rem)] items-center gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-muted';
              return (
                <li key={f.id}>
                  {onSelectFinding ? (
                    <button type="button" onClick={() => onSelectFinding(f)} className={cls} title="See this problem">
                      {row}
                    </button>
                  ) : (
                    <Link to={`${base}&finding=${encodeURIComponent(f.id)}`} className={cls}>
                      {row}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {perObject.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">By object</p>
          <div className="flex flex-wrap gap-1.5">
            {perObject.map((o) => {
              const cls = 'inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs transition hover:border-brand/40 hover:text-brand';
              const chip = (
                <>
                  <span className={cx('h-1.5 w-1.5 rounded-full', DOT[o.tone])} />
                  <span className="font-medium">{o.label}</span>
                  <span className="text-ink-subtle">{o.text}</span>
                </>
              );
              return onSelectObject ? (
                <button key={o.name} type="button" onClick={() => onSelectObject(o)} className={cls} title={`See ${o.label} problems in this area`}>
                  {chip}
                </button>
              ) : (
                <Link key={o.name} to={`${base}&object=${encodeURIComponent(o.name)}`} className={cls} title={`See problems for ${o.label}`}>
                  {chip}
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
