import { CATEGORIES, getAreasForCategory } from '@/config/categories';
import type { AssessmentResults, CategoryId, Finding, Severity } from '@/types';

/** Pure helpers that derive UI values from backend results. No data is invented here. */

export const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low'];
export const SEVERITY_RANK: Record<Severity, number> = { critical: 4, high: 3, medium: 2, low: 1 };

export function countBySeverity(findings: Finding[] = []) {
  const out: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const f of findings) out[f.severity]++;
  return out;
}

export const getAreaResult = (results: AssessmentResults | undefined | null, areaId: string) =>
  results?.areas.find((a) => a.areaId === areaId);

/** Category score as reported by the backend, falling back to the mean of assessed area scores. */
export function getCategoryScore(results: AssessmentResults | undefined | null, id: CategoryId): number | null {
  if (!results) return null;
  const reported = results.categories.find((c) => c.categoryId === id)?.score;
  if (reported !== undefined && reported !== null) return reported;
  const scores = getAreasForCategory(id)
    .map((a) => getAreaResult(results, a.id)?.score)
    .filter((s): s is number => typeof s === 'number');
  return scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null;
}

export type CoverageStatus = 'not-assessed' | 'partial' | 'assessed';

export function getCategoryCoverage(results: AssessmentResults | undefined | null, id: CategoryId): CoverageStatus {
  if (!results) return 'not-assessed';
  const areas = getAreasForCategory(id);
  const done = areas.filter((a) => getAreaResult(results, a.id)?.status === 'assessed').length;
  if (done === 0) return 'not-assessed';
  return done === areas.length ? 'assessed' : 'partial';
}

export const COVERAGE_LABEL: Record<CoverageStatus, string> = {
  'not-assessed': 'Not checked yet',
  partial: 'Partly checked',
  assessed: 'Checked',
};

export const findingsForCategory = (findings: Finding[] | undefined, id: CategoryId) =>
  (findings ?? []).filter((f) => f.categoryId === id);

export const findingsForArea = (findings: Finding[] | undefined, areaId: string) =>
  (findings ?? []).filter((f) => f.areaId === areaId);

export const categoryScores = (results: AssessmentResults | undefined | null) =>
  CATEGORIES.map((c) => ({ category: c, score: getCategoryScore(results, c.id) }));

export function delta(current: number | null | undefined, previous: number | null | undefined) {
  return current === null || current === undefined || previous === null || previous === undefined ? null : current - previous;
}

/** Percentage change, rounded; null when there is no baseline. */
export function pctChange(current: number | null | undefined, previous: number | null | undefined) {
  if (current == null || previous == null || previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}
