import { useMemo, useRef, useState, type ReactNode } from 'react';
import { ColumnFilter, type ValuesSource } from '@/components/data/ColumnFilter';
import { useExpand } from '@/components/ui/Expand';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, DataFilter } from '@/types';

type Cell = string | number | boolean | null | undefined;

/** One column: its heading, the value it filters and sorts on, and (optionally) how its cell looks. */
export type LocalColumn<R> = {
  key: string;
  label: ReactNode;
  /** The column's plain name for its filter ("Filter Type"); defaults to `label` when that's text. */
  name?: string;
  value: (row: R) => Cell;
  render?: (row: R) => ReactNode;
  align?: 'right';
  /** Classes for the column's cells (width, wrapping…). */
  className?: string;
  /** false: no Excel-style filter on this column (e.g. long text). */
  filter?: boolean;
};

const blank = (v: Cell) => v == null || v === '';
const same = (a: unknown, b: unknown) => a === b || (blank(a as Cell) && blank(b as Cell));

/**
 * A table of rows already in the browser with the records tables' Excel-style column filters (each value with its count,
 * search, Select all, (Blanks)), sorting from the same drop-down, a row count, Clear filters and an Expand button.
 */
export function LocalTable<R>({
  title,
  rows,
  columns,
  rowKey,
  empty = 'Nothing to show.',
  actions,
  maxHeight = 'max-h-[32rem]',
  tone,
}: {
  title: ReactNode;
  rows: R[];
  columns: LocalColumn<R>[];
  rowKey: (row: R) => string;
  empty?: string;
  /** Extra controls in the header, before the row count (e.g. a view switch). */
  actions?: ReactNode;
  maxHeight?: string;
  /** The header's colour (e.g. red for "Action required"). */
  tone?: 'bad';
}) {
  const ex = useExpand();
  const [filters, setFilters] = useState<DataFilter[]>([]);
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(null);
  // a new key for the filters' value lists whenever the rows change, so their counts are never stale
  const version = useRef(0);
  const rowsKey = useMemo(() => ++version.current, [rows]);
  const colOf = (key: string) => columns.find((c) => c.key === key);

  const keep = (r: R, f: DataFilter) => {
    const col = colOf(f.field);
    if (!col) return true;
    const v = col.value(r);
    if (f.op === 'blank') return blank(v);
    const listed = ((f.value as unknown[]) ?? []).some((x) => same(x, v));
    return f.op === 'in' ? listed : !listed;
  };
  const filtered = rows.filter((r) => filters.every((f) => keep(r, f)));
  const shown = !sort
    ? filtered
    : [...filtered].sort((a, b) => {
        const col = colOf(sort.key)!;
        const x = col.value(a);
        const y = col.value(b);
        if (blank(x) !== blank(y)) return blank(x) ? 1 : -1; // blanks last
        const n = typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? ''), undefined, { numeric: true });
        return sort.dir === 'asc' ? n : -n;
      });

  const source: ValuesSource = {
    key: ['local-table', rowsKey],
    load: async (field, others) => {
      const col = colOf(field)!;
      const counts = new Map<string, { value: string | number | boolean; label: string; count: number }>();
      let blanks = 0;
      for (const r of rows.filter((row) => others.every((f) => keep(row, f)))) {
        const v = col.value(r);
        if (blank(v)) {
          blanks++;
          continue;
        }
        const k = JSON.stringify(v);
        const hit = counts.get(k);
        if (hit) hit.count++;
        else counts.set(k, { value: v as string | number | boolean, label: String(v), count: 1 });
      }
      const values = [...counts.values()].sort((a, b) =>
        typeof a.value === 'number' && typeof b.value === 'number' ? a.value - b.value : a.label.localeCompare(b.label, undefined, { numeric: true }),
      );
      return { field, values, blanks, truncated: false };
    },
  };
  const fieldOf = (c: LocalColumn<R>): DataField => ({
    name: c.key,
    label: c.name ?? (typeof c.label === 'string' ? c.label : c.key),
    type: 'string',
    custom: false,
    required: false,
    sortable: true,
    filterable: true,
    column: true,
    referenceTo: [],
    helpText: null,
    picklistValues: [],
    groupable: true,
  });
  const setColumn = (key: string, f: DataFilter | null) => setFilters((all) => [...all.filter((x) => x.field !== key), ...(f ? [f] : [])]);

  return ex.wrap(
    <section className={cx('overflow-hidden rounded-xl border', tone === 'bad' ? 'border-bad/40' : 'border-line', ex.boxClass)}>
      <div className={cx('flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs', tone === 'bad' ? 'bg-bad-soft text-bad' : 'bg-muted/40')}>
        <span className={cx('font-semibold', tone === 'bad' ? 'text-bad' : 'text-ink')}>{title}</span>
        <span className="flex flex-wrap items-center gap-2">
          {actions}
          <span className="text-ink-muted">
            {filters.length ? `${fmtNumber(shown.length)} of ${fmtNumber(rows.length)}` : fmtNumber(rows.length)}
          </span>
          {(filters.length > 0 || sort) && (
            <button type="button" onClick={() => (setFilters([]), setSort(null))} className="text-brand hover:underline">
              Clear filters
            </button>
          )}
          {ex.button}
        </span>
      </div>
      <div className={ex.scrollClass(maxHeight)}>
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 z-10 bg-surface text-xs text-ink-muted">
            <tr className="border-b border-line">
              {columns.map((c) => (
                <th key={c.key} className={cx('whitespace-nowrap px-3 py-2 font-medium', c.align === 'right' && 'text-right')}>
                  <span className={cx('inline-flex items-center', c.align === 'right' && 'justify-end')}>
                    {c.label}
                    {c.filter !== false && (
                      <ColumnFilter
                        object="local"
                        field={fieldOf(c)}
                        search=""
                        filters={filters}
                        onApply={(f) => setColumn(c.key, f)}
                        onSort={(dir) => setSort({ key: c.key, dir })}
                        source={source}
                      />
                    )}
                    {sort?.key === c.key && <span className="ml-0.5 text-[10px] text-brand">{sort.dir === 'asc' ? '▲' : '▼'}</span>}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {!shown.length && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-6 text-center text-xs text-ink-subtle">
                  {rows.length ? 'No rows match these filters.' : empty}
                </td>
              </tr>
            )}
            {shown.map((r) => (
              <tr key={rowKey(r)} className="align-top hover:bg-muted/40">
                {columns.map((c) => (
                  <td key={c.key} className={cx('px-3 py-2', c.align === 'right' && 'text-right tabular-nums', c.className)}>
                    {c.render ? c.render(r) : blank(c.value(r)) ? '—' : String(c.value(r))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filters.length > 0 && (
        <p className="border-t border-line px-3 py-1.5 text-[11px] text-ink-subtle">Filtered: {filters.map((f) => f.label).join(' · ')}</p>
      )}
    </section>,
  );
}
