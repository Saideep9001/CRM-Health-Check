import { motion } from 'framer-motion';
import { Cloud } from 'lucide-react';
import { CATEGORIES, CATEGORY_COLORS } from '@/config/categories';
import { CategoryIcon } from '../ui/CategoryIcon';
import { LogoGlyph } from '../ui/Brand';

/**
 * Abstract, animated illustration of the platform: Salesforce data flowing into
 * the assessment engine, which fans out to the six categories. Purely decorative —
 * it shows no scores or results.
 */
export function HeroVisual() {
  const R = 150;
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[460px]" aria-hidden="true">
      {/* Soft glow */}
      <div className="absolute inset-[18%] rounded-full bg-brand/20 blur-3xl" />

      {/* Orbit rings */}
      <div className="absolute inset-[8%] rounded-full border border-line" />
      <div className="absolute inset-[22%] rounded-full border border-dashed border-line" />
      <div
        className="absolute inset-[8%] animate-sweep rounded-full"
        style={{
          background: 'conic-gradient(from 0deg, transparent 0deg, rgb(var(--brand)) 45deg, transparent 80deg)',
          opacity: 0.14,
          maskImage: 'radial-gradient(circle, transparent 60%, black 61%)',
          WebkitMaskImage: 'radial-gradient(circle, transparent 60%, black 61%)',
        }}
      />

      {/* Connection lines with flowing dashes */}
      <svg viewBox="-230 -230 460 460" className="absolute inset-0 h-full w-full">
        {CATEGORIES.map((c, i) => {
          const a = (i / CATEGORIES.length) * Math.PI * 2 - Math.PI / 2;
          return (
            <line
              key={c.id}
              x1={0}
              y1={0}
              x2={Math.cos(a) * R}
              y2={Math.sin(a) * R}
              stroke={CATEGORY_COLORS[c.id]}
              strokeOpacity={c.release === 'mvp' ? 0.55 : 0.2}
              strokeWidth={1.5}
              strokeDasharray="4 8"
              className="animate-flow"
            />
          );
        })}
        {/* Pulses travelling outward */}
        {CATEGORIES.filter((c) => c.release === 'mvp').map((c, i) => {
          const idx = CATEGORIES.indexOf(c);
          const a = (idx / CATEGORIES.length) * Math.PI * 2 - Math.PI / 2;
          return (
            <motion.circle
              key={c.id}
              r={3.5}
              fill={CATEGORY_COLORS[c.id]}
              initial={{ cx: 0, cy: 0, opacity: 0 }}
              animate={{ cx: [0, Math.cos(a) * R], cy: [0, Math.sin(a) * R], opacity: [0, 1, 0] }}
              transition={{ duration: 2.2, repeat: Infinity, delay: i * 0.55, ease: 'easeOut' }}
            />
          );
        })}
      </svg>

      {/* Category nodes */}
      {CATEGORIES.map((c, i) => {
        const a = (i / CATEGORIES.length) * Math.PI * 2 - Math.PI / 2;
        const x = 50 + (Math.cos(a) * R * 100) / 460;
        const y = 50 + (Math.sin(a) * R * 100) / 460;
        return (
          <motion.div
            key={c.id}
            className="absolute -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${x}%`, top: `${y}%` }}
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.3 + i * 0.1, type: 'spring', stiffness: 260, damping: 18 }}
          >
            <motion.div
              animate={{ y: [0, -5, 0] }}
              transition={{ duration: 4 + i * 0.3, repeat: Infinity, ease: 'easeInOut' }}
              className="flex flex-col items-center gap-1.5"
            >
              <span
                className="flex h-12 w-12 items-center justify-center rounded-2xl border border-line bg-surface shadow-pop"
                style={{ color: CATEGORY_COLORS[c.id], opacity: c.release === 'mvp' ? 1 : 0.55 }}
              >
                <CategoryIcon id={c.id} className="h-5 w-5" />
              </span>
              <span className="whitespace-nowrap rounded-full bg-surface/90 px-2 py-0.5 text-[10px] font-semibold text-ink-muted shadow-card">
                {c.shortName}
              </span>
            </motion.div>
          </motion.div>
        );
      })}

      {/* Core engine */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
        <span className="absolute inset-0 animate-pulse-ring rounded-3xl border-2 border-brand" />
        <motion.span
          initial={{ scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 220, damping: 16 }}
          className="relative flex h-20 w-20 items-center justify-center rounded-3xl bg-brand text-white shadow-pop"
        >
          <LogoGlyph className="h-11 w-11" />
        </motion.span>
      </div>

      {/* Salesforce source badge */}
      <motion.div
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 1 }}
        className="absolute -left-2 bottom-[6%] flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 shadow-pop sm:left-0"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#00a1e0] text-white">
          <Cloud className="h-4 w-4" />
        </span>
        <span className="text-left leading-tight">
          <span className="block text-xs font-semibold">Salesforce Sales Cloud</span>
          <span className="block text-[10px] text-ink-subtle">Read-only access</span>
        </span>
      </motion.div>
    </div>
  );
}
