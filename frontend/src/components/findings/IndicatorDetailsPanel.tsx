import { AlertTriangle, ArrowRight, Database, Info, ListChecks, Search } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { indicatorApi } from '@/api/endpoints';
import { useIndicatorRecords } from '@/api/queries';
import { SEVERITY_COLORS } from '@/components/charts/Charts';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { DiagnosticArea, Finding, IndicatorValue, Severity } from '@/types';
import { Drawer } from '../ui/Overlay';
import { ScoreRing } from '../ui/Visuals';
import { RecordsTable } from './RecordsTable';

/** Same thresholds the engine uses (backend/app/engine/core.py → severity_for, finding min_score). */
const PROBLEM_BELOW = 95;
const URGENCY: { severity: Severity; label: string; range: string }[] = [
  { severity: 'critical', label: 'Critical', range: 'below 40' },
  { severity: 'high', label: 'High', range: '40–59' },
  { severity: 'medium', label: 'Medium', range: '60–79' },
  { severity: 'low', label: 'Low', range: '80–94' },
];
const urgencyFor = (score: number): Severity => (score < 40 ? 'critical' : score < 60 ? 'high' : score < 80 ? 'medium' : 'low');

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

/** The rule table: one row per rule, label on the left, exact detail on the right. */
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

/** One "What we measure" card opened: what we count, the exact rules (as a table), and the records behind the number. */
export function IndicatorDetailsPanel({
  area,
  indicator,
  assessmentId,
  checkedAt,
  findings,
  onClose,
  onOpenFinding,
  onCheckAgain,
}: {
  area: DiagnosticArea;
  indicator: IndicatorValue | null;
  /** The health check that measured this area (may be earlier than the latest one). */
  assessmentId: string | null;
  checkedAt: string | null;
  /** This area's problems. */
  findings: Finding[];
  onClose: () => void;
  onOpenFinding: (f: Finding) => void;
  /** Scroll to "Check again" (for results from older checks that don't carry the rules yet). */
  onCheckAgain?: () => void;
}) {
  const objects = indicator?.recordObjects ?? [];
  const [object, setObject] = useState<string | null>(objects[0] ?? null);
  useEffect(() => setObject(indicator?.recordObjects?.[0] ?? null), [indicator]);
  const records = useIndicatorRecords(indicator ? assessmentId : null, area.id, indicator?.label ?? '', object);

  const v = indicator;
  const scored = v?.score != null;
  const legacy = !!v && !v.how && !v.rule && !(v.criteria ?? []).length;
  const related = v
    ? findings.filter((f) => f.status !== 'resolved' && f.status !== 'accepted-risk' && (!objects.length || !f.objectName || objects.includes(f.objectName)))
    : [];
  const duplicates = !!v && /duplicate/i.test(v.label);

  const urgency = scored && v!.score! < PROBLEM_BELOW ? URGENCY.find((u) => u.severity === urgencyFor(v!.score!))! : null;
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
              {urgency ? (
                <span className="font-semibold" style={{ color: SEVERITY_COLORS[urgency.severity] }}>{urgency.label} problem</span>
              ) : (
                <span className="font-semibold text-good">no problem raised</span>
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

  return (
    <Drawer
      open={!!v}
      onClose={onClose}
      wide
      title={v?.label ?? ''}
      subtitle={<span className="text-xs text-ink-subtle">Area {area.number}: {area.name}{checkedAt ? ` · checked ${fmtDate(checkedAt)}` : ''}</span>}
    >
      {v && (
        <>
          {/* the number and its score */}
          <div className="mb-6 flex flex-wrap items-center gap-6 rounded-xl border border-line bg-muted/40 p-5">
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-subtle">Result</p>
              <p className="mt-1 text-4xl font-semibold tabular-nums tracking-tight">
                {fmtNumber(v.value)}
                {v.unit === '%' && <span className="text-xl text-ink-subtle">%</span>}
              </p>
              <p className="mt-1 text-xs text-ink-muted">{v.direction === 'higher-better' ? 'Higher is better' : 'Lower is better'}</p>
            </div>
            {scored && (
              <div className="flex items-center gap-4">
                <ScoreRing score={Math.round(v.score!)} size={88} stroke={8} label="Score" showBand={false} />
                <span
                  className={cx('inline-flex items-center gap-1.5 text-xs font-semibold', !urgency && 'text-good')}
                  style={urgency ? { color: SEVERITY_COLORS[urgency.severity] } : undefined}
                >
                  {urgency && <AlertTriangle className="h-3.5 w-3.5" />}
                  {urgency ? `${urgency.label} problem` : 'No problem raised'}
                </span>
              </div>
            )}
          </div>

          {legacy && (
            <div className="mb-6 flex flex-wrap items-center gap-3 rounded-lg border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn">
              <Info className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1">
                This result is from a health check run before the rules were recorded. Check this area again to see the exact rules and the records behind the number.
              </span>
              {onCheckAgain && (
                <button type="button" onClick={onCheckAgain} className="rounded-md bg-warn px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110">
                  Check this area again
                </button>
              )}
            </div>
          )}

          <Section icon={<Search className="h-3.5 w-3.5" />} title="What we measure">
            <p>{v.how ?? area.description}</p>
          </Section>

          <Section icon={<ListChecks className="h-3.5 w-3.5" />} title="How it’s flagged — the exact rules">
            <RuleTable rows={ruleRows} />
          </Section>

          <Section icon={<Database className="h-3.5 w-3.5" />} title="The records behind this number">
            {objects.length === 0 ? (
              <p className="rounded-lg bg-muted/50 px-4 py-3 text-sm text-ink-muted">
                {legacy
                  ? 'Check this area again to list the records behind this number.'
                  : 'This measure looks at settings or a summary across records, so there isn’t a list of records to show. The rules above say exactly what was inspected.'}
              </p>
            ) : (
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
                {object && assessmentId && (
                  <RecordsTable
                    query={records}
                    title={objectLabel(object)}
                    grouped={duplicates}
                    csvUrl={indicatorApi.csvUrl(assessmentId, area.id, v.label, object)}
                  />
                )}
                <p className="mt-2 text-[11px] text-ink-subtle">
                  {duplicates ? 'Each shaded block is one duplicate group (#group · records in it). ' : ''}
                  Read live from Salesforce with the connected user’s access. Click a name to open the record.
                </p>
              </>
            )}
          </Section>

          {related.length > 0 && (
            <Section icon={<AlertTriangle className="h-3.5 w-3.5" />} title="Problems raised in this area">
              <ul className="space-y-1">
                {related.slice(0, 6).map((f) => (
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
          )}
        </>
      )}
    </Drawer>
  );
}
