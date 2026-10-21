import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import type { ReactNode } from 'react';
import type { SortDir } from '@/hooks/useSort';
import { cx } from '@/lib/format';

export function SortableTh<K extends string>({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
  align = 'left',
  className,
}: {
  label: ReactNode;
  sortKey: K;
  activeKey: K;
  dir: SortDir;
  onSort: (k: K) => void;
  align?: 'left' | 'right';
  className?: string;
}) {
  const active = sortKey === activeKey;
  const Icon = !active ? ArrowUpDown : dir === 'asc' ? ArrowUp : ArrowDown;
  return (
    <th className={cx('th', className)} aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button
        onClick={() => onSort(sortKey)}
        className={cx(
          'inline-flex items-center gap-1 uppercase tracking-wide transition hover:text-ink',
          active && 'text-ink',
          align === 'right' && 'flex-row-reverse',
        )}
      >
        {label}
        <Icon className={cx('h-3 w-3', !active && 'opacity-40')} />
      </button>
    </th>
  );
}

export function TableShell({ children }: { children: ReactNode }) {
  return (
    <div className="scrollbar-thin relative overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse">{children}</table>
    </div>
  );
}
