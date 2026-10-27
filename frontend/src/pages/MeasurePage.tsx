import { useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { finderFor } from '@/components/findings/DuplicateFinder';
import { FieldCheck } from '@/components/findings/FieldCheck';
import { IndicatorDetailsPanel } from '@/components/findings/IndicatorDetailsPanel';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { getArea } from '@/config/categories';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { findingsForArea, getAreaResult } from '@/lib/health';
import type { FieldCheckResult } from '@/types';
import NotFoundPage from './NotFoundPage';

/** One measure ("What we measure") on its own page: rules, records, the problem it raised, and a field check (empty values, duplicates, spellings). */
export default function MeasurePage() {
  const { areaId = '' } = useParams();
  const [params] = useSearchParams();
  const label = params.get('label') ?? '';
  const object = params.get('object');
  const navigate = useNavigate();
  const [checked, setChecked] = useState<FieldCheckResult | null>(null); // the latest Check fields run
  const [shown, setShown] = useState<string[] | null>(null); // fields ticked in Check fields for the records table (null = all)
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
  const finder = finderFor(indicator.label, indicator.criteria);

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
      extra={objects.length > 0 && finder && (
        <FieldCheck objects={objects} initialObject={object ?? objects[0]} focus={finder.kind} fieldsText={finder.fieldsText} onResult={setChecked}
          shownFields={shown} onPickFields={setShown} recordFields={(indicator?.fieldScores ?? []).map((s) => s.field)} />
      )}
      fieldCheck={checked}
      onClearFieldCheck={() => setChecked(null)}
      shownFields={shown}
    />
  );
}
