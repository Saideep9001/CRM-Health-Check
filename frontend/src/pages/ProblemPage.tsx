import { useNavigate, useParams } from 'react-router-dom';
import { useAssessmentResults, useFinding, useFindings } from '@/api/queries';
import { measureFor } from '@/components/findings/DetailsPanel';
import { finderFor } from '@/components/findings/DuplicateFinder';
import { FieldCheck } from '@/components/findings/FieldCheck';
import { FindingDetailsPanel } from '@/components/findings/FindingDetailsPanel';
import { ErrorState, LoadingState } from '@/components/ui/States';

/** One problem on its own page: the full details, the records, and a field check (empty values, duplicates, spellings) for its object. */
export default function ProblemPage() {
  const { findingId = '' } = useParams();
  const navigate = useNavigate();
  const finding = useFinding(findingId);
  const f = finding.data ?? null;
  const results = useAssessmentResults(f?.assessmentId ?? null, !!f);
  const all = useFindings(f?.assessmentId ?? null, !!f);
  const indicator = f ? measureFor(f, results.data?.areas.find((a) => a.areaId === f.areaId)?.indicators ?? []) : null;
  // The problem's own object (a problem is about one object), as the check looked at it.
  const objects = f?.objectName ? [f.objectName] : indicator?.recordObjects ?? [];
  const finder = f ? finderFor(`${f.name} ${indicator?.label ?? ''}`, indicator?.criteria) : null;

  if (finding.isLoading) return <LoadingState rows={6} label="Loading the problem…" />;
  if (finding.error || !f) return <ErrorState error={finding.error} onRetry={() => finding.refetch()} />;

  return (
    <FindingDetailsPanel
      asPage
      finding={f}
      others={all.data ?? []}
      onClose={() => (window.history.length > 1 ? navigate(-1) : navigate('/results'))}
      onOpenFinding={(o) => navigate(`/problems/${encodeURIComponent(o.id)}`)}
      extra={objects.length > 0 && <FieldCheck objects={objects} initialObject={f.objectName ?? objects[0]} focus={finder?.kind} fieldsText={finder?.fieldsText} />}
    />
  );
}
