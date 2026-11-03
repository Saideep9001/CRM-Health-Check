import { motion } from 'framer-motion';
import { ArrowRight, Layers, TriangleAlert } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { CATEGORY_COLORS } from '@/config/categories';
import { fmtNumber, scoreBand } from '@/lib/format';
import { SEVERITY_RANK, findingsForCategory, getCategoryCoverage, getCategoryScore } from '@/lib/health';
import type { AssessmentResults, Category, Finding } from '@/types';
import { CoverageBadge, ReleaseBadge } from '../ui/Badges';
import { Button } from '../ui/Button';
import { InfoTip } from '../ui/HelpTip';
import { CategoryTile } from '../ui/CategoryIcon';
import { ScoreRing } from '../ui/Visuals';

export function CategoryCard({
  category,
  results,
  findings,
}: {
  category: Category;
  results: AssessmentResults | null;
  findings: Finding[];
}) {
  const navigate = useNavigate();
  const score = getCategoryScore(results, category.id);
  const coverage = getCategoryCoverage(results, category.id);
  const mine = findingsForCategory(findings, category.id);
  const count = mine.length;
  const biggest = [...mine].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.affectedRecords - a.affectedRecords)[0];
  const color = CATEGORY_COLORS[category.id];
  const soon = category.release === 'coming-soon';
  const band = scoreBand(score);

  return (
    <motion.article
      whileHover={{ y: -4 }}
      transition={{ type: 'spring', stiffness: 380, damping: 26 }}
      className="card group relative flex h-full flex-col overflow-hidden"
    >
      {/* colour accent bar */}
      <span className="absolute inset-x-0 top-0 h-1" style={{ background: color, opacity: soon ? 0.35 : 1 }} />

      <div className="flex flex-1 flex-col p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <CategoryTile id={category.id} />
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">Topic {category.order} of 6</p>
              <ReleaseBadge release={category.release} />
            </div>
          </div>
          {score !== null ? (
            <ScoreRing score={score} size={58} stroke={6} showBand={false} />
          ) : (
            <span className="flex h-[58px] w-[58px] items-center justify-center rounded-full border-2 border-dashed border-line text-[10px] font-medium text-ink-subtle">
              {soon ? 'Soon' : 'N/A'}
            </span>
          )}
        </div>

        <h3 className="mt-4 text-[15px] font-semibold leading-snug">
          {category.name}{' '}
          <InfoTip label={`About ${category.name}`}>{category.purpose}</InfoTip>
        </h3>
        <div className="flex-1" />

        {/* This topic's own biggest problem: what to look at first */}
        {coverage !== 'not-assessed' && !soon && (
          biggest ? (
            <button
              type="button"
              onClick={() => navigate(`/problems/${encodeURIComponent(biggest.id)}`)}
              className="mt-3 rounded-lg border border-line px-3 py-2 text-left text-xs transition hover:border-brand/40 hover:bg-muted/50"
            >
              <span className="block text-[10px] font-semibold uppercase tracking-wide text-ink-subtle">Biggest problem · {biggest.severity}</span>
              <span className="mt-0.5 block font-medium text-ink">{biggest.name}</span>
              {biggest.affectedRecords > 0 && (
                <span className="block text-ink-muted">
                  {fmtNumber(biggest.affectedRecords)} {biggest.objectName ? `${biggest.objectName} ` : ''}records affected
                </span>
              )}
            </button>
          ) : (
            <p className="mt-3 rounded-lg bg-good-soft/60 px-3 py-2 text-xs text-good">No problems found in this topic.</p>
          )
        )}

        {/* Stats grid */}
        <dl className="mt-4 grid grid-cols-3 gap-2 rounded-lg bg-muted/70 p-3 text-center">
          <div>
            <dt className="flex items-center justify-center gap-1 text-[11px] text-ink-subtle">
              <Layers className="h-3 w-3" />
              Areas
            </dt>
            <dd className="mt-0.5 text-sm font-semibold">{category.areaIds.length}</dd>
          </div>
          <div>
            <dt className="flex items-center justify-center gap-1 text-[11px] text-ink-subtle">
              <TriangleAlert className="h-3 w-3" />
              Problems
            </dt>
            <dd className="mt-0.5 text-sm font-semibold">{coverage === 'not-assessed' ? '—' : count}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-subtle" title="Health score: 100% means no problems were found">
              Score
            </dt>
            <dd className="mt-0.5 text-sm font-semibold" style={{ color: band.color }}>
              {score !== null ? `${score}%` : '—'}
            </dd>
          </div>
        </dl>

        <div className="mt-4 flex items-center justify-between gap-2">
          <CoverageBadge status={coverage} />
          <Button
            size="sm"
            variant="ghost"
            onClick={() => navigate(`/assessment/${category.id}`)}
            iconRight={<ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />}
            aria-label={`View details for ${category.name}`}
          >
            View details
          </Button>
        </div>
      </div>
    </motion.article>
  );
}
