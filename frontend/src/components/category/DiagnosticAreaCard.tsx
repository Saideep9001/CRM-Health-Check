import { motion } from 'framer-motion';
import { ArrowRight, CalendarDays, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { SEVERITY_COLORS } from '@/components/charts/Charts';
import { SEVERITY_RANK } from '@/lib/health';
import { getAreaRelease } from '@/config/categories';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { AreaResult, DiagnosticArea, Finding, ObjectResult } from '@/types';
import { Badge, ReleaseBadge } from '../ui/Badges';
import { Button } from '../ui/Button';
import { InfoTip } from '../ui/HelpTip';
import { AnimatedNumber, ScoreRing } from '../ui/Visuals';
import type { IndicatorValue } from '@/types';

/** A card's colour from its score, in the urgency bands: green 80 or more (no problem, or Low), orange 40–79 (Medium or
 *  High), red below 40 (Critical). */
export function cardTone(score: number): 'good' | 'warn' | 'bad' {
  return score >= 80 ? 'good' : score >= 40 ? 'warn' : 'bad';
}

/** Rough health of one number, for the coloured dot only (the area score is the real measure). */
function indicatorTone(i: IndicatorValue): 'good' | 'warn' | 'bad' {
  if (i.score != null) return cardTone(i.score);
  if (i.unit === '%') {
    const good = i.direction === 'higher-better' ? i.value : 100 - i.value;
    return good >= 90 ? 'good' : good >= 70 ? 'warn' : 'bad';
  }
  if (i.direction === 'lower-better') return i.value === 0 ? 'good' : i.value <= 10 ? 'warn' : 'bad';
  return i.value > 0 ? 'good' : 'warn';
}

const DOT = { good: 'bg-good', warn: 'bg-warn', bad: 'bg-bad' };
/** A measure's score as a tinted chip (no bar): the tone shows at a glance, the number counts up. */
const CHIP = { good: 'bg-good-soft text-good ring-good/20', warn: 'bg-warn-soft text-warn ring-warn/20', bad: 'bg-bad-soft text-bad ring-bad/20' };

/** What the measure counted, for the tooltip on its score (e.g. "45" or "98%"). */
const counted = (i: IndicatorValue) => `${fmtNumber(Math.round(i.value))}${i.unit === '%' ? '%' : ''}`;

/** Does a measure belong to an object ("Missing Key Fields (Accounts)", "Duplicate Accounts", "Accounts Without Contacts")? */
export function measureOf(label: string, plural: string) {
  return label.endsWith(`(${plural})`) || label === `Duplicate ${plural}` || label === `Stale ${plural}` || label.startsWith(`${plural} Without`);
}

/** The measure's name without its object: "Missing Key Fields (Accounts)" → "Missing Key Fields". */
function shortName(label: string, plural: string) {
  return label.replace(` (${plural})`, '').replace(`Duplicate ${plural}`, 'Duplicates').replace(`${plural} Without`, 'Without');
}

export const URGENCY_HELP = 'Urgency of the problem a measure raised. Critical: blocks the sales process or affects most records, fix now. High: causes wrong numbers or lost deals. Medium: slows people down or makes reports less reliable. Low: tidy-up. No badge: no problem raised.';
const URGENCY_CLASS: Record<string, string> = { critical: 'bg-bad-soft text-bad', high: 'bg-warn-soft text-warn', medium: 'bg-warn-soft/60 text-warn', low: 'bg-brand-soft text-brand-ink' };
const DATA_QUALITY_AREAS = new Set(['area-1', 'area-2']);

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
  // Data Quality areas: one object at a time, chosen on the card (score and measures follow it).
  const perObject = DATA_QUALITY_AREAS.has(area.id);
  const measures = (result?.indicators ?? []).filter((i) => i.label !== 'Data Quality Scorecard');
  const checkedObjects = perObject ? objects.filter((o) => measures.some((i) => measureOf(i.label, o.label))) : [];
  const [picked, setPicked] = useState<string | null>(null);
  const current = checkedObjects.find((o) => o.name === picked) ?? checkedObjects[0];
  const shown = current
    ? measures.filter((i) => measureOf(i.label, current.label))
    : measures.filter((i) => area.indicators.includes(i.label)).slice(0, 3);
  const scored = shown.filter((i) => i.score != null).map((i) => i.score!);
  const shownScore = current && scored.length ? Math.round(scored.reduce((a, b) => a + b, 0) / scored.length) : result?.score ?? null;
  const urgencyOf = (label: string) => findings.find((f) => f.measure === label && f.status !== 'resolved' && f.status !== 'accepted-risk')?.severity;
  const objectProblems = current ? findings.filter((f) => f.objectName === current.name).length : findingsCount;

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

      {assessed && result.score !== null && checkedObjects.length > 1 && (
        <div className="mt-4 flex flex-wrap gap-1" role="tablist" aria-label="Object">
          {checkedObjects.map((o) => (
            <button
              key={o.name}
              type="button"
              role="tab"
              aria-selected={o.name === current?.name}
              onClick={() => setPicked(o.name)}
              className={cx('rounded-full border px-2.5 py-0.5 text-xs font-medium transition',
                o.name === current?.name ? 'border-brand bg-brand-soft text-brand-ink' : 'border-line text-ink-muted hover:border-brand/40 hover:text-ink')}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}

      {assessed && result.score !== null ? (
        <div className="mt-4 flex items-start gap-4">
          <div className="shrink-0 text-center">
            <ScoreRing score={shownScore ?? result.score} size={72} stroke={7} showBand={false} />
            {current && <p className="mt-1 text-[10px] text-ink-subtle">{current.label}</p>}
          </div>
          <ul className="min-w-0 flex-1 space-y-1">
            {current && (
              <li className="flex items-center gap-1 pb-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-subtle">
                What we measured on {current.label}
                <InfoTip label="What the badges mean">{URGENCY_HELP}</InfoTip>
              </li>
            )}
            {shown.map((i, n) => {
              const urgency = urgencyOf(i.label);
              return (
                <motion.li
                  key={`${current?.name ?? ''}-${i.label}`} // switching object replays the entrance
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: n * 0.04, duration: 0.25, ease: 'easeOut' }}
                >
                  <button
                    type="button"
                    disabled={!onSelectMeasure}
                    onClick={() => onSelectMeasure?.(i.label)}
                    className="group/m -mx-1.5 flex w-[calc(100%+0.75rem)] items-center gap-2 rounded-md px-1.5 py-0.5 text-left text-xs enabled:hover:bg-muted"
                    title={onSelectMeasure ? 'See the rules and the records behind this number' : undefined}
                  >
                    <span className={cx('h-1.5 w-1.5 shrink-0 rounded-full', DOT[indicatorTone(i)])} />
                    <span className="min-w-0 flex-1 truncate text-ink-muted group-enabled/m:group-hover/m:text-brand" title={i.label}>
                      {current ? shortName(i.label, current.label) : i.label}
                    </span>
                    {urgency && <span className={cx('shrink-0 rounded px-1.5 py-px text-[9px] font-semibold uppercase', URGENCY_CLASS[urgency])}>{urgency}</span>}
                    {i.score != null ? (
                      <span
                        className={cx('min-w-[3rem] shrink-0 rounded-full px-2 py-px text-center font-semibold tabular-nums ring-1 transition-transform group-enabled/m:group-hover/m:scale-105', CHIP[cardTone(i.score)])}
                        title={`Score ${Math.round(i.score)}% · counted: ${counted(i)}`}
                      >
                        <AnimatedNumber value={Math.round(i.score)} duration={0.8} />%
                      </span>
                    ) : (
                      <span className="min-w-[3rem] shrink-0 text-center font-semibold tabular-nums" title="Shown for information; not scored">
                        <AnimatedNumber value={Math.round(i.value)} duration={0.8} />
                        {i.unit === '%' ? '%' : ''}
                      </span>
                    )}
                  </button>
                </motion.li>
              );
            })}
          </ul>
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-dashed border-line px-3 py-2 text-xs text-ink-subtle">
          {release === 'coming-soon'
            ? 'This area can be checked in a later release.'
            : result?.message ?? 'Not checked yet — include it in your next health check.'}
        </div>
      )}

      {/* Other areas: their most urgent problems and objects (Data Quality cards list every measure above instead) */}
      {assessed && assessmentId && !current && (
        <AreaExtras areaId={area.id} findings={findings} objects={objects} assessmentId={assessmentId} onSelectFinding={onSelectFinding} onSelectObject={onSelectObject} />
      )}

      <div className="flex-1" />

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1">
          <TriangleAlert className="h-3.5 w-3.5" />
          {assessed ? `${objectProblems} problem${objectProblems === 1 ? '' : 's'}${current ? ` on ${current.label}` : ''}` : 'No problems'}
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
