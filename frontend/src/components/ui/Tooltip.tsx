import type { ReactNode } from 'react';
import { cx } from '@/lib/format';

/** CSS-only tooltip; shows on hover and keyboard focus. */
export function Tooltip({
  content,
  children,
  side = 'top',
  className,
}: {
  content: ReactNode;
  children: ReactNode;
  side?: 'top' | 'bottom' | 'right';
  className?: string;
}) {
  const pos = {
    top: 'bottom-full left-1/2 mb-2 -translate-x-1/2',
    bottom: 'top-full left-1/2 mt-2 -translate-x-1/2',
    right: 'left-full top-1/2 ml-2 -translate-y-1/2',
  }[side];
  return (
    <span className={cx('group/tt relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        className={cx(
          'pointer-events-none absolute z-50 w-max max-w-[240px] rounded-md bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white opacity-0 shadow-pop transition-opacity duration-150 group-focus-within/tt:opacity-100 group-hover/tt:opacity-100 dark:bg-slate-700',
          pos,
        )}
      >
        {content}
      </span>
    </span>
  );
}
