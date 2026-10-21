import { useAssessmentResults, useCompletedAssessments, useFindings } from '@/api/queries';

/**
 * Latest completed assessment with its results and findings.
 * `state` collapses the three queries into one value pages can switch on.
 */
export function useLatestAssessment() {
  const list = useCompletedAssessments();
  const latest = list.data?.[0] ?? null;
  const previous = list.data?.[1] ?? null;
  const results = useAssessmentResults(latest?.id ?? null);
  const findings = useFindings(latest?.id ?? null);

  const error = list.error ?? results.error ?? findings.error ?? null;
  const loading = list.isLoading || (!!latest && (results.isLoading || findings.isLoading));

  const state: 'loading' | 'error' | 'empty' | 'ready' = loading
    ? 'loading'
    : error
      ? 'error'
      : !latest
        ? 'empty'
        : 'ready';

  return {
    state,
    error,
    latest,
    previous,
    history: list.data ?? [],
    results: results.data ?? null,
    findings: findings.data ?? [],
    refetch: () => {
      list.refetch();
      if (latest) {
        results.refetch();
        findings.refetch();
      }
    },
  };
}
