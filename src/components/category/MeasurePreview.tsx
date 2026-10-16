import { motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';
import { SectionCard } from '@/components/ui/Page';
import type { DiagnosticArea } from '@/types';

/** Before the first check: what this topic will measure, area by area. */
export function MeasurePreview({ areas, color }: { areas: DiagnosticArea[]; color: string }) {
  return (
    <SectionCard className="mb-6" title="What we’ll measure" description="Run a check to fill these in with numbers from your Salesforce.">
      <div className="grid gap-4 md:grid-cols-2">
        {areas.map((a, i) => (
          <motion.div
            key={a.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08 }}
            className="rounded-xl border border-dashed border-line p-4"
          >
            <p className="mb-2.5 flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="h-4 w-4" style={{ color }} />
              Area {a.number}: {a.name}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {a.indicators.map((label, j) => (
                <motion.span
                  key={label}
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: i * 0.08 + j * 0.04 }}
                  className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-muted"
                >
                  {label}
                </motion.span>
              ))}
            </div>
          </motion.div>
        ))}
      </div>
    </SectionCard>
  );
}
