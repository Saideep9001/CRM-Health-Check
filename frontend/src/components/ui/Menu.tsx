import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { cx } from '@/lib/format';

/** Click-to-open dropdown with outside-click and Escape handling. */
export function Dropdown({
  trigger,
  children,
  align = 'right',
  width = 'w-64',
}: {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: 'left' | 'right';
  width?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.14 }}
            className={cx(
              'card absolute top-full z-50 mt-2 overflow-hidden p-1 shadow-pop',
              width,
              align === 'right' ? 'right-0 origin-top-right' : 'left-0 origin-top-left',
            )}
            role="menu"
          >
            {children(() => setOpen(false))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function MenuItem({
  icon,
  children,
  onClick,
  hint,
  danger,
}: {
  icon?: ReactNode;
  children: ReactNode;
  onClick: () => void;
  hint?: ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className={cx(
        'flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition hover:bg-muted',
        danger ? 'text-bad' : 'text-ink',
      )}
    >
      {icon && <span className="text-ink-subtle">{icon}</span>}
      <span className="flex-1">{children}</span>
      {hint}
    </button>
  );
}
