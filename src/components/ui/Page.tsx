import { motion } from 'framer-motion';
import { Info, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import { cx } from '@/lib/format';
import { InfoTip } from './HelpTip';

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-2 flex flex-wrap items-center gap-2">{eyebrow}</div>}
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          {title}
          {description && (
            <InfoTip size="md" label="About this page">
              {description}
            </InfoTip>
          )}
        </h1>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const NOTICE_TONES = {
  info: { box: 'border-brand/25 bg-brand-soft', icon: 'text-brand', Icon: Info },
  warn: { box: 'border-warn/30 bg-warn-soft', icon: 'text-warn', Icon: TriangleAlert },
  neutral: { box: 'border-line bg-muted', icon: 'text-ink-subtle', Icon: Info },
};

/** Inline page-level notice (e.g. "Coming Soon", "Salesforce not connected"). */
export function Notice({
  tone = 'info',
  title,
  children,
  action,
  icon,
  className,
}: {
  tone?: keyof typeof NOTICE_TONES;
  title?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  const t = NOTICE_TONES[tone];
  return (
    <div className={cx('mb-6 flex flex-col gap-3 rounded-xl border px-4 py-3 text-sm sm:flex-row sm:items-center', t.box, className)}>
      <div className="flex flex-1 items-start gap-3">
        <span className={cx('mt-0.5 shrink-0', t.icon)}>{icon ?? <t.Icon className="h-4 w-4" />}</span>
        <p className="text-ink-muted">
          {title && <span className="font-semibold text-ink">{title} </span>}
          {children}
        </p>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function SectionCard({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cx('card', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            {title && (
              <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                {title}
                {description && <InfoTip label="About this section">{description}</InfoTip>}
              </h2>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cx('p-5', bodyClassName)}>{children}</div>
    </section>
  );
}

/** Staggered reveal for grids of cards. */
export const stagger = {
  container: { hidden: {}, show: { transition: { staggerChildren: 0.05 } } },
  item: {
    hidden: { opacity: 0, y: 12 },
    show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] } },
  },
};

export function StaggerGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div variants={stagger.container} initial="hidden" animate="show" className={className}>
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div variants={stagger.item} className={className}>
      {children}
    </motion.div>
  );
}
