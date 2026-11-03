import { Maximize2, Minimize2 } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cx } from '@/lib/format';

/**
 * Expand a table to the whole browser window and back. Every records table uses this:
 * put `button` in its header, wrap the table in `wrap(...)`, and while `big` let its scroll area grow (`scrollClass`).
 * Esc or Minimize closes it; the page behind doesn't scroll while it's open.
 */
export function useExpand(disabled = false) {
  const [big, setBig] = useState(false);
  useEffect(() => {
    if (!big) return;
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setBig(false);
    const scroll = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', esc);
    return () => {
      document.body.style.overflow = scroll;
      document.removeEventListener('keydown', esc);
    };
  }, [big]);

  const button = (
    <button
      type="button"
      onClick={() => setBig((b) => !b)}
      disabled={disabled && !big}
      title={big ? 'Back to the page (Esc)' : 'Show this table on the whole page'}
      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink-muted hover:border-brand/40 hover:text-brand disabled:opacity-50"
    >
      {big ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
      {big ? 'Minimize' : 'Expand'}
    </button>
  );

  /** The table itself, or (expanded) the table over the whole window, outside any side panel. */
  const wrap = (node: ReactNode) =>
    big ? createPortal(<div className="fixed inset-0 z-[55] flex flex-col bg-surface p-3 sm:p-5">{node}</div>, document.body) : node;

  /** Classes for the table's own box and its scroll area: normal height on the page, the whole window when expanded. */
  const boxClass = big ? 'flex min-h-0 flex-1 flex-col' : '';
  const scrollClass = (normal: string) => cx('scrollbar-thin overflow-auto', big ? 'min-h-0 flex-1' : normal);

  return { big, button, wrap, boxClass, scrollClass };
}
