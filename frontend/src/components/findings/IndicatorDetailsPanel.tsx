import { SEVERITY_RANK } from '@/lib/health';
import type { DiagnosticArea, Finding, IndicatorValue } from '@/types';
import { DetailsPanel, findingsFor } from './DetailsPanel';

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
}) {
  const open = findings.filter((f) => f.status !== 'resolved' && f.status !== 'accepted-risk');
  const raised = indicator
    ? findingsFor(indicator, findings).sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords)
    : [];
  const main = raised[0] ?? null;

  return (
    <DetailsPanel
      open={!!indicator}
      area={area}
      indicator={indicator}
      finding={main}
      measureAssessmentId={assessmentId}
      checkedAt={checkedAt}
      // The measure's other problems first (e.g. Contacts and Leads without a phone), then the rest of the area.
      others={[...raised.slice(1), ...open.filter((f) => !raised.includes(f))]}
      onClose={onClose}
      onOpenFinding={onOpenFinding}
      onCheckAgain={onCheckAgain}
    />
  );
}
