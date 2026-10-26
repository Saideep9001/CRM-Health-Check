import { SEVERITY_RANK } from '@/lib/health';
import type { DiagnosticArea, Finding, IndicatorValue } from '@/types';
import { DetailsPanel, findingsFor } from './DetailsPanel';
import type { FieldCheckResult } from '@/types';

/** A "What we measure" card opened: the one details panel, with the problem it raised (if any). */
export function IndicatorDetailsPanel({
  area,
  indicator,
  assessmentId,
  checkedAt,
  findings,
  onClose,
  onOpenFinding,
  onCheckAgain,
  object,
  asPage,
  extra,
  fieldCheck,
  onClearFieldCheck,
  shownFields,
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
  onCheckAgain?: () => void;
  /** Opened from a "By object" chip: that object's problem and records come first. */
  object?: string | null;
  asPage?: boolean;
  extra?: React.ReactNode;
  fieldCheck?: FieldCheckResult | null;
  onClearFieldCheck?: () => void;
  shownFields?: string[];
}) {
  const open = findings.filter((f) => f.status !== 'resolved' && f.status !== 'accepted-risk');
  const bySeverity = (a: Finding, b: Finding) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords;
  const raised = indicator ? findingsFor(indicator, findings).sort(bySeverity) : [];
  const objectFindings = object ? open.filter((f) => f.objectName === object).sort(bySeverity) : [];
  // From a chip: this measure's problem on that object (never a different measure's problem); that object's other problems come next.
  const main = (object ? raised.find((f) => f.objectName === object) : raised[0]) ?? null;
  const first = [...raised, ...objectFindings].filter((f, i, all) => f !== main && all.indexOf(f) === i);

  return (
    <DetailsPanel
      open={!!indicator}
      area={area}
      indicator={indicator}
      finding={main}
      measureAssessmentId={assessmentId}
      checkedAt={checkedAt}
      // The measure's other problems first (e.g. Contacts and Leads without a phone), then the rest of the area.
      others={[...first, ...open.filter((f) => f !== main && !first.includes(f))]}
      onClose={onClose}
      onOpenFinding={onOpenFinding}
      onCheckAgain={onCheckAgain}
      initialObject={object}
      asPage={asPage}
      extra={extra}
      fieldCheck={fieldCheck}
      onClearFieldCheck={onClearFieldCheck}
      shownFields={shownFields}
    />
  );
}
