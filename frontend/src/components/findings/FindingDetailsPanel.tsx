import { useAssessmentResults } from '@/api/queries';
import { getArea } from '@/config/categories';
import type { Finding } from '@/types';
import { DetailsPanel, measureFor } from './DetailsPanel';

/** A problem opened anywhere (My Results, topic pages…): the one details panel, with the measure that raised it. */
export function FindingDetailsPanel({
  finding,
  onClose,
  others,
  onOpenFinding,
}: {
  finding: Finding | null;
  onClose: () => void;
  /** Other problems to offer at the bottom (optional). */
  others?: Finding[];
  onOpenFinding?: (f: Finding) => void;
}) {
  const results = useAssessmentResults(finding?.assessmentId ?? null, !!finding);
  const areaRes = finding ? results.data?.areas.find((a) => a.areaId === finding.areaId) : undefined;
  const indicator = finding && areaRes ? measureFor(finding, areaRes.indicators) : null;

  return (
    <DetailsPanel
      open={!!finding}
      area={finding ? getArea(finding.areaId) : undefined}
      indicator={indicator}
      finding={finding}
      measureAssessmentId={areaRes?.sourceAssessmentId ?? finding?.assessmentId ?? null}
      checkedAt={areaRes?.checkedAt ?? null}
      others={(others ?? []).filter((f) => f.areaId === finding?.areaId && f.status !== 'resolved' && f.status !== 'accepted-risk')}
      onClose={onClose}
      onOpenFinding={onOpenFinding}
    />
  );
}
