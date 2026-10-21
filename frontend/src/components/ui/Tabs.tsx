import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { cx } from '@/lib/format';

export interface TabDef<T extends string> {
  id: T;
  label: string;
  icon?: ReactNode;
  count?: number;
}

/** Underline tabs with an animated active indicator. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  layoutId = 'tabs',
}: {
  tabs: TabDef<T>[];
  value: T;
  onChange: (v: T) => void;
  layoutId?: string;
}) {
  return (
    <div role="tablist" className="scrollbar-thin flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={cx(
              'relative flex shrink-0 items-center gap-2 px-3 pb-2.5 pt-2 text-sm font-medium transition',
              active ? 'text-brand' : 'text-ink-muted hover:text-ink',
            )}
          >
            {t.icon}
            {t.label}
            {t.count !== undefined && (
              <span className={cx('rounded-full px-1.5 text-[11px]', active ? 'bg-brand-soft text-brand-ink' : 'bg-muted text-ink-subtle')}>
                {t.count}
              </span>
            )}
            {active && (
              <motion.span layoutId={layoutId} className="absolute inset-x-1 -bottom-px h-0.5 rounded-full bg-brand" />
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Pill-style segmented control. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  layoutId = 'seg',
}: {
  options: { id: T; label: string; icon?: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  layoutId?: string;
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-muted p-0.5" role="radiogroup">
      {options.map((o) => {
        const active = o.id === value;
        return (
          <button
            key={o.id}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.id)}
            className={cx(
              'relative flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition',
              active ? 'text-ink' : 'text-ink-muted hover:text-ink',
            )}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-0 rounded-md bg-surface shadow-card"
                transition={{ type: 'spring', stiffness: 500, damping: 35 }}
              />
            )}
            <span className="relative flex items-center gap-1.5">
              {o.icon}
              {o.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
