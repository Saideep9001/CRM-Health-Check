import type { ReactNode } from 'react';
import { CATEGORIES, CATEGORY_COLORS, getArea, getCategory } from '@/config/categories';
import { fmtDate, fmtNumber, scoreBand } from '@/lib/format';
import { countBySeverity, findingsForCategory, getCategoryScore, SEVERITIES, SEVERITY_RANK } from '@/lib/health';
import type { Assessment, AssessmentResults, Finding, ReportType } from '@/types';
import { CategoryHealthChart, FindingsBySeverityChart, ScoreTrendChart, SEVERITY_COLORS } from '../charts/Charts';
import { AssessmentStatusBadge, SeverityBadge } from '../ui/Badges';
import { ScoreRing } from '../ui/Visuals';
import { BrandedFooter, BrandedHeader, useBranding } from './Branding';

export const REPORT_TITLES: Record<ReportType, string> = {
  executive: 'Summary for leadership',
  category: 'Score by topic',
  findings: 'Full list of problems',
  severity: 'Problems by urgency',
  history: 'Health check history',
  proposal: 'Proposal & statement of work',
};

function H({ children }: { children: ReactNode }) {
  return <h3 className="mb-3 mt-6 text-sm font-semibold uppercase tracking-wide text-ink-subtle first:mt-0">{children}</h3>;
}

/** Printable, document-styled preview generated from assessment data. */
export function ReportPreview({
  type,
  assessment,
  results,
  findings,
  history,
  scopeLabel,
}: {
  type: ReportType;
  assessment: Assessment | null;
  results: AssessmentResults | null;
  findings: Finding[];
  history: Assessment[];
  scopeLabel: string;
}) {
  const branding = useBranding();
  const sev = countBySeverity(findings);
  const categoriesWithFindings = new Set(findings.map((f) => f.categoryId)).size;
  const score = results?.overallScore ?? assessment?.overallScore ?? null;

  return (
    <article className="relative mx-auto max-w-4xl overflow-hidden rounded-xl border border-line bg-surface shadow-card">
      <BrandedHeader
        branding={branding}
        title={REPORT_TITLES[type]}
        subtitle={`${type === 'history' ? 'All organizations' : `${assessment?.organizationName} · ${assessment?.name}`} · ${scopeLabel}`}
        right={type !== 'history' ? <p>{findings.length} problems included</p> : null}
      />

      <div className="px-8 py-6">
        {type === 'executive' && assessment && (
          <>
            <div className="grid items-center gap-6 sm:grid-cols-[auto,1fr]">
              <ScoreRing score={score} size={128} stroke={10} label="Overall" />
              <div>
                <H>Summary</H>
                <p className="text-sm leading-relaxed text-ink-muted">
                  {score !== null ? (
                    <>
                      {assessment.organizationName} has an overall CRM health score of{' '}
                      <strong className="text-ink">{score}/100</strong> ({scoreBand(score).label.toLowerCase()}).{' '}
                    </>
                  ) : (
                    'No overall score was produced for this health check. '
                  )}
                  This health check reviewed {fmtNumber(results?.recordsAssessed ?? assessment.recordsAssessed ?? 0)} records and identified{' '}
                  {findings.length} problems across {categoriesWithFindings} {categoriesWithFindings === 1 ? 'topic' : 'topics'}, including{' '}
                  {sev.critical} critical and {sev.high} high-urgency problems.
                </p>
              </div>
            </div>
            <H>Fix these first</H>
            {findings.length === 0 ? (
              <p className="text-sm text-ink-subtle">No problems in this report.</p>
            ) : (
              <ol className="space-y-2">
                {[...findings]
                  .sort((a, b) => a.priority.localeCompare(b.priority) || SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords)
                  .slice(0, 5)
                  .map((f, i) => (
                    <li key={f.id} className="flex items-start gap-3 text-sm">
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand text-[11px] font-bold text-white">{i + 1}</span>
                      <span className="flex-1">
                        <span className="font-medium">{f.name}</span>
                        <span className="block text-ink-muted">{f.recommendedAction}</span>
                      </span>
                      <SeverityBadge severity={f.severity} />
                    </li>
                  ))}
              </ol>
            )}
            <H>Score trend</H>
            <ScoreTrendChart assessments={history} height={200} />
          </>
        )}

        {type === 'category' && (
          <>
            <CategoryHealthChart results={results} height={240} />
            <H>Score by topic</H>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line">
                  <th className="th px-0">Topic</th>
                  <th className="th">Areas</th>
                  <th className="th">Problems</th>
                  <th className="th">Score</th>
                </tr>
              </thead>
              <tbody>
                {CATEGORIES.map((c) => {
                  const s = getCategoryScore(results, c.id);
                  const assessed = assessment?.scope.categoryIds.includes(c.id);
                  return (
                    <tr key={c.id} className="border-b border-line last:border-0">
                      <td className="py-2.5">
                        <span className="flex items-center gap-2">
                          <span className="h-2 w-2 rounded-full" style={{ background: CATEGORY_COLORS[c.id] }} />
                          {c.name}
                        </span>
                      </td>
                      <td className="px-4 tabular-nums">{c.areaIds.length}</td>
                      <td className="px-4 tabular-nums">{assessed ? findingsForCategory(findings, c.id).length : '—'}</td>
                      <td className="px-4 font-semibold tabular-nums" style={{ color: scoreBand(s).color }}>
                        {s ?? (c.release === 'mvp' ? 'Not checked' : 'Coming Soon')}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}

        {type === 'findings' &&
          (findings.length === 0 ? (
            <p className="text-sm text-ink-subtle">No problems in this report.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line">
                  <th className="th px-0">ID</th>
                  <th className="th">Problem</th>
                  <th className="th">Severity</th>
                  <th className="th text-right">Records</th>
                </tr>
              </thead>
              <tbody>
                {[...findings]
                  .sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity])
                  .map((f) => (
                    <tr key={f.id} className="border-b border-line align-top last:border-0">
                      <td className="py-2.5 font-mono text-xs text-ink-muted">{f.id}</td>
                      <td className="px-4 py-2.5">
                        <p className="font-medium">{f.name}</p>
                        <p className="text-xs text-ink-subtle">
                          {getCategory(f.categoryId)?.shortName} · Area {getArea(f.areaId)?.number} — {f.recommendedAction}
                        </p>
                      </td>
                      <td className="px-4 py-2.5">
                        <SeverityBadge severity={f.severity} />
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{fmtNumber(f.affectedRecords)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          ))}

        {type === 'severity' && (
          <>
            <FindingsBySeverityChart findings={findings} size={200} />
            {findings.length > 0 && (
              <>
                <H>Affected records by severity</H>
                <div className="space-y-3">
                  {(() => {
                    const totals = SEVERITIES.map((s) => findings.filter((f) => f.severity === s).reduce((a, f) => a + f.affectedRecords, 0));
                    const max = Math.max(1, ...totals);
                    return SEVERITIES.map((s, i) => (
                      <div key={s} className="flex items-center gap-3 text-sm">
                        <span className="w-20 capitalize text-ink-muted">{s}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${(totals[i] / max) * 100}%`, background: SEVERITY_COLORS[s] }} />
                        </div>
                        <span className="w-20 text-right tabular-nums">{fmtNumber(totals[i])}</span>
                      </div>
                    ));
                  })()}
                </div>
              </>
            )}
          </>
        )}

        {type === 'history' && (
          <>
            <ScoreTrendChart assessments={history} height={200} />
            <H>Health checks in this period</H>
            {history.length === 0 ? (
              <p className="text-sm text-ink-subtle">No health checks in this period.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line">
                    <th className="th px-0">Health check</th>
                    <th className="th">Organization</th>
                    <th className="th">Date</th>
                    <th className="th">Problems</th>
                    <th className="th">Score</th>
                    <th className="th">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((a) => (
                    <tr key={a.id} className="border-b border-line last:border-0">
                      <td className="py-2.5 font-medium">{a.name}</td>
                      <td className="px-4 text-ink-muted">{a.organizationName}</td>
                      <td className="px-4 text-ink-muted">{fmtDate(a.completedAt ?? a.createdAt)}</td>
                      <td className="px-4 tabular-nums">{a.findingsCount ?? '—'}</td>
                      <td className="px-4 tabular-nums">{a.overallScore ?? '—'}</td>
                      <td className="px-4">
                        <AssessmentStatusBadge status={a.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>

      <BrandedFooter branding={branding} />
    </article>
  );
}
