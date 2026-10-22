import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { DuplicateFinder } from '@/components/findings/DuplicateFinder';
import { IndicatorDetailsPanel } from '@/components/findings/IndicatorDetailsPanel';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { getArea } from '@/config/categories';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { findingsForArea, getAreaResult } from '@/lib/health';
import NotFoundPage from './NotFoundPage';

/** One measure ("What we measure") on its own page: rules, records, the problem it raised, and a duplicate finder. */
export default function MeasurePage() {
  const { areaId = '' } = useParams();
  const [params] = useSearchParams();
  const label = params.get('label') ?? '';
  const object = params.get('object');
  const navigate = useNavigate();
  const area = getArea(areaId);
  const { state, error, refetch, latest, results, findings } = useLatestAssessment();

  if (!area) return <NotFoundPage />;
  if (state === 'loading') return <LoadingState rows={6} label="Loading…" />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;

  const result = getAreaResult(results, area.id);
  const indicator = result?.indicators.find((i) => i.label === label) ?? null;
  if (!indicator) {
    return <EmptyState className="py-16" title="This measure isn’t in your latest results" description="Run a health check on this area to see it." />;
  }
  const objects = indicator.recordObjects ?? [];

  return (
    <IndicatorDetailsPanel
      asPage
      area={area}
      indicator={indicator}
      object={object}
      assessmentId={result?.sourceAssessmentId ?? latest?.id ?? null}
      checkedAt={result?.checkedAt ?? latest?.completedAt ?? null}
      findings={findingsForArea(findings, area.id)}
      onClose={() => (window.history.length > 1 ? navigate(-1) : navigate(`/assessment/${area.categoryId}/${area.id}`))}
      onCheckAgain={() => navigate(`/assessment/${area.categoryId}/${area.id}`)}
      onOpenFinding={(f) => navigate(`/problems/${encodeURIComponent(f.id)}`)}
      extra={objects.length > 0 && <DuplicateFinder objects={objects} initialObject={object ?? objects[0]} />}
    />
  );
}
