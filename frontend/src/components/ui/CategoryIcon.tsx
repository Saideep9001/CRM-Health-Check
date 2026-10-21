import { BarChart3, Database, FileText, Plug, Users, Workflow, type LucideProps } from 'lucide-react';
import { CATEGORY_COLORS } from '@/config/categories';
import { cx } from '@/lib/format';
import type { CategoryId } from '@/types';

const ICONS = {
  'data-quality': Database,
  workflows: Workflow,
  reporting: BarChart3,
  'user-adoption': Users,
  quoting: FileText,
  integrations: Plug,
} as const;

export function CategoryIcon({ id, ...props }: { id: CategoryId } & LucideProps) {
  const Icon = ICONS[id];
  return <Icon {...props} />;
}

/** Tinted rounded tile with the category's icon. */
export function CategoryTile({ id, size = 'md' }: { id: CategoryId; size?: 'sm' | 'md' | 'lg' }) {
  const color = CATEGORY_COLORS[id];
  const dims = { sm: 'h-8 w-8', md: 'h-10 w-10', lg: 'h-12 w-12' }[size];
  const icon = { sm: 'h-4 w-4', md: 'h-5 w-5', lg: 'h-6 w-6' }[size];
  return (
    <span
      className={cx('inline-flex shrink-0 items-center justify-center rounded-lg', dims)}
      style={{ background: `${color}1f`, color }}
    >
      <CategoryIcon id={id} className={icon} />
    </span>
  );
}
