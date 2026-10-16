import { motion } from 'framer-motion';
import { ArrowRight, CalendarCheck2 } from 'lucide-react';
import { CATEGORIES, CATEGORY_COLORS } from '@/config/categories';
import { fmtDate, scoreBand } from '@/lib/format';
import { getCategoryScore } from '@/lib/health';
import type { Assessment, AssessmentResults } from '@/types';
import { LinkButton } from '../ui/Button';
import { ScoreLegend } from '../ui/ScoreLegend';
import { ScoreRing } from '../ui/Visuals';

/** Radar sweep with orbiting category markers around a centre element. */
export function RadarFrame({ color, children, dim }: { color: string; children: React.ReactNode; dim?: boolean }) {
  return (
    <div className="relative mx-auto flex h-[220px] w-[220px] items-center justify-center">
      <div className="absolute inset-0 rounded-full border border-line" />
      <div className="absolute inset-[22px] rounded-full border border-dashed border-line" />
      <div
        className="absolute inset-0 animate-sweep rounded-full"
        style={{
          background: `conic-gradient(from 0deg, transparent 0deg, ${color} 40deg, transparent 70deg)`,
          opacity: dim ? 0.08 : 0.16,
          maskImage: 'radial-gradient(circle, transparent 54%, black 55%)',
          WebkitMaskImage: 'radial-gradient(circle, transparent 54%, black 55%)',
        }}
      />
      {CATEGORIES.map((c, i) => {
        const angle = (i / CATEGORIES.length) * Math.PI * 2 - Math.PI / 2;
        return (
          <motion.span
            key={c.id}
            className="absolute h-2.5 w-2.5 rounded-full ring-2 ring-surface"
            style={{
              background: CATEGORY_COLORS[c.id],
              left: 110 + Math.cos(angle) * 104 - 5,
              top: 110 + Math.sin(angle) * 104 - 5,
              opacity: dim || c.release !== 'mvp' ? 0.35 : 1,
            }}
            initial={{ scale: 0 }}
            animate={{ scale: [1, 1.35, 1] }}
            transition={{ delay: 0.4 + i * 0.12, duration: 2.4, repeat: Infinity, repeatDelay: 1.2 }}
          />
        );
      })}
      {children}
    </div>
  );
}

const Dots = () => (
  <div
    className="pointer-events-none absolute inset-0 opacity-50 dark:opacity-35"
    style={{
      backgroundImage: 'radial-gradient(circle at 1px 1px, rgb(var(--line)) 1px, transparent 0)',
      backgroundSize: '22px 22px',
      maskImage: 'linear-gradient(90deg, transparent, black 30%, black 70%, transparent)',
    }}
  />
);

/** Executive hero for the latest completed assessment. */
export function HealthHero({ assessment, results }: { assessment: Assessment; results: AssessmentResults }) {
  const score = results.overallScore ?? assessment.overallScore;
  const band = scoreBand(score);
  return (
    <section className="card relative overflow-hidden">
      <Dots />
      <div className="relative grid gap-8 p-6 md:grid-cols-[auto,1fr] md:items-center lg:p-8">
        <RadarFrame color={band.color}>
          <ScoreRing score={score} size={164} stroke={12} label="Overall health" showBand={false} />
        </RadarFrame>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-ink-muted">
              <CalendarCheck2 className="h-3.5 w-3.5" /> {assessment.name} · {fmtDate(assessment.completedAt ?? assessment.createdAt)}
            </span>
            <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-semibold" style={{ color: band.color }}>
              {band.label}
            </span>
          </div>
          <h2 className="mt-3 text-xl font-semibold tracking-tight lg:text-2xl">{assessment.organizationName}</h2>
          <p className="mt-1.5 max-w-2xl text-sm text-ink-muted">
            Org ID {assessment.orgId} · {assessment.scope.areaIds.length} areas across{' '}
            {assessment.scope.categoryIds.length} topics checked.
          </p>

          <div className="mt-5 grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
            {CATEGORIES.map((c, i) => {
              const s = getCategoryScore(results, c.id);
              return (
                <div key={c.id} className="min-w-0">
                  <div className="flex items-center justify-between text-xs">
                    <span className="flex min-w-0 items-center gap-1.5 text-ink-muted">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: CATEGORY_COLORS[c.id] }} />
                      <span className="truncate">{c.shortName}</span>
                    </span>
                    <span className="font-semibold tabular-nums">
                      {s ?? <span className="font-medium text-ink-subtle">{c.release === 'mvp' ? 'N/A' : 'Soon'}</span>}
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: CATEGORY_COLORS[c.id] }}
                      initial={{ width: 0 }}
                      animate={{ width: `${s ?? 0}%` }}
                      transition={{ duration: 1.1, delay: 0.3 + i * 0.08, ease: [0.16, 1, 0.3, 1] }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          <ScoreLegend className="mt-5" />

          <div className="mt-5 flex flex-wrap gap-2">
            <LinkButton to={`/results?assessment=${assessment.id}`} variant="primary" iconRight={<ArrowRight className="h-4 w-4" />}>
              See problems to fix
            </LinkButton>
            <LinkButton to="/assessment">See all topics</LinkButton>
          </div>
        </div>
      </div>
    </section>
  );
}

export { Dots as HeroDots };
