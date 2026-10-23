import { ArrowDownAZ, ArrowUpAZ, ChevronDown, Filter, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { errorMessage } from '@/api/client';
import { useFieldValues } from '@/api/queries';
import { cx, fmtDate, fmtNumber } from '@/lib/format';
import type { DataField, DataFilter } from '@/types';

const BLANK = '__blank__';
const MAX_PICK = 100; // values one filter can name (the rest are left out instead, like Excel)
const keyOf = (v: unknown) => JSON.stringify(v);

/** The filter a column has from its own drop-down ("is one of", "is not one of", or empty), if any. */
export function columnFilter(filters: DataFilter[], field: string): DataFilter | undefined {
  return filters.find((f) => f.field === field && (f.op === 'in' || f.op === 'notin' || f.op === 'blank'));
}

function show(field: DataField, value: unknown, label: string): string {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return fmtNumber(value);
  if (field.type === 'date' && typeof value === 'string') return fmtDate(value);
  return label;
}

/**
 * Excel-style filter for one column: every value in the column with how many records have it, a search box,
 * Select all, and (Blanks). Counts follow the search box and the other columns' filters.
 */
export function ColumnFilter({
  object,
  field,
  search,
  filters,
  onApply,
  onSort,
}: {
  object: string;
  field: DataField;
  search: string;
  filters: DataFilter[];
  onApply: (filter: DataFilter | null) => void;
  onSort?: (dir: 'asc' | 'desc') => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number; maxHeight: number }>({ top: 0, left: 0, maxHeight: 440 });
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const current = columnFilter(filters, field.name);
  const others = useMemo(() => filters.filter((f) => f.field !== field.name), [filters, field.name]);
  const values = useFieldValues(object, open ? field.name : null, search, others);

  const items = useMemo(() => {
    const list = (values.data?.values ?? []).map((v) => ({ key: keyOf(v.value), value: v.value as unknown, text: show(field, v.value, v.label), count: v.count }));
    if (values.data?.blanks) list.push({ key: BLANK, value: null, text: '(Blanks)', count: values.data.blanks });
    return list;
  }, [values.data, field]);

  // Start from what the column's filter keeps (or everything).
  useEffect(() => {
    if (!open || !values.data) return;
    const all = new Set(items.map((i) => i.key));
    if (!current) setPicked(all);
    else if (current.op === 'blank') setPicked(new Set([BLANK]));
    else {
      const named = new Set(((current.value as unknown[]) ?? []).map((v) => (v === null ? BLANK : keyOf(v))));
      setPicked(new Set(current.op === 'in' ? [...all].filter((k) => named.has(k)) : [...all].filter((k) => !named.has(k))));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, values.data]);

  // Close on a click outside, Escape, or when the column scrolls away from under it.
  useEffect(() => {
    if (!open) return;
    const outside = (e: Event) => {
      if (!panel.current?.contains(e.target as Node) && !button.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const start = button.current?.getBoundingClientRect();
    const moved = () => {
      const now = button.current?.getBoundingClientRect();
      if (!start || !now || Math.abs(now.top - start.top) > 2 || Math.abs(now.left - start.left) > 2) setOpen(false);
    };
    document.addEventListener('mousedown', outside);
    document.addEventListener('scroll', moved, true);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', outside);
      document.removeEventListener('scroll', moved, true);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  const toggle = () => {
    if (!open && button.current) {
      const r = button.current.getBoundingClientRect();
      const left = Math.max(8, Math.min(r.left - 8, window.innerWidth - 300));
      const below = window.innerHeight - r.bottom - 14;
      // Open downwards like Excel; upwards when there's little room below. The list shrinks to fit.
      if (below >= 300 || below >= r.top - 14) setPos({ top: r.bottom + 6, left, maxHeight: Math.min(440, below) });
      else setPos({ bottom: window.innerHeight - r.top + 6, left, maxHeight: Math.min(440, r.top - 14) });
      setQuery('');
      setPicked(null);
    }
    setOpen((o) => !o);
  };

  const term = query.trim().toLowerCase();
  const visible = term ? items.filter((i) => i.text.toLowerCase().includes(term)) : items;
  const sel = picked ?? new Set<string>();
  const allVisibleOn = visible.length > 0 && visible.every((i) => sel.has(i.key));
  const setMany = (keys: string[], on: boolean) =>
    setPicked((p) => {
      const n = new Set(p ?? []);
      keys.forEach((k) => (on ? n.add(k) : n.delete(k)));
      return n;
    });

  const kept = items.filter((i) => sel.has(i.key));
  const left = items.filter((i) => !sel.has(i.key));
  const useIn = kept.length <= left.length;
  const named = useIn ? kept : left;
  const tooMany = left.length > 0 && named.length > MAX_PICK;

  const apply = () => {
    if (!left.length) onApply(null);
    else if (kept.length === 1 && kept[0].key === BLANK) onApply({ field: field.name, op: 'blank', label: `${field.label}: (Blanks)` });
    else {
      const names = named.map((i) => i.text);
      const shown = names.slice(0, 3).join(', ') + (names.length > 3 ? ` +${names.length - 3} more` : '');
      onApply({ field: field.name, op: useIn ? 'in' : 'notin', value: named.map((i) => i.value), label: `${field.label}: ${useIn ? '' : 'not '}${shown}` });
    }
    setOpen(false);
  };

  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          toggle();
        }}
        aria-label={`Filter ${field.label}`}
        aria-expanded={open}
        title={current ? `Filtered: ${current.label ?? ''}` : `Filter ${field.label}`}
        className={cx(
          'ml-1 inline-grid h-5 w-5 place-items-center rounded transition',
          current ? 'bg-brand text-white' : 'text-ink-subtle hover:bg-surface hover:text-ink',
        )}
      >
        {current ? <Filter className="h-3 w-3" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            role="dialog"
            aria-label={`Filter ${field.label}`}
            style={{ top: pos.top, bottom: pos.bottom, left: pos.left, maxHeight: pos.maxHeight }}
            className="fixed z-50 flex w-72 flex-col rounded-xl border border-line bg-surface p-3 text-sm normal-case tracking-normal text-ink shadow-pop"
          >
            {onSort && field.sortable && (
              <div className="mb-2 grid grid-cols-2 gap-1.5 border-b border-line pb-2">
                <button type="button" onClick={() => (onSort('asc'), setOpen(false))} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs hover:bg-muted">
                  <ArrowDownAZ className="h-3.5 w-3.5" /> Sort A → Z
                </button>
                <button type="button" onClick={() => (onSort('desc'), setOpen(false))} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs hover:bg-muted">
                  <ArrowUpAZ className="h-3.5 w-3.5" /> Sort Z → A
                </button>
              </div>
            )}
            <div className="relative mb-2">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
              <input autoFocus className="input h-8 pl-8 text-xs" placeholder="Search values…" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
            {values.isLoading || !picked ? (
              values.error ? (
                <p className="py-4 text-center text-xs text-bad">{errorMessage(values.error)}</p>
              ) : (
                <p className="py-6 text-center text-xs text-ink-muted">Reading the values…</p>
              )
            ) : (
              <>
                <label className="flex cursor-pointer items-center gap-2 border-b border-line px-1 pb-1.5 text-xs font-semibold">
                  <input type="checkbox" className="h-3.5 w-3.5 accent-[rgb(var(--brand))]" checked={allVisibleOn} onChange={(e) => setMany(visible.map((i) => i.key), e.target.checked)} />
                  {term ? 'Select all search results' : 'Select all'}
                </label>
                <div className="scrollbar-thin mt-1 max-h-64 min-h-[3rem] flex-1 overflow-y-auto">
                  {visible.map((i) => (
                    <label key={i.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-xs hover:bg-muted">
                      <input type="checkbox" className="h-3.5 w-3.5 shrink-0 accent-[rgb(var(--brand))]" checked={sel.has(i.key)} onChange={(e) => setMany([i.key], e.target.checked)} />
                      <span className={cx('min-w-0 flex-1 truncate', i.key === BLANK && 'italic text-ink-muted')} title={i.text}>
                        {i.text}
                      </span>
                      <span className="shrink-0 tabular-nums text-ink-subtle">{fmtNumber(i.count)}</span>
                    </label>
                  ))}
                  {visible.length === 0 && <p className="py-3 text-center text-xs text-ink-subtle">No values match “{query}”.</p>}
                </div>
                {values.data?.truncated && <p className="mt-1 text-[11px] text-ink-subtle">Showing the 2,000 most common values.</p>}
                {tooMany && <p className="mt-1 text-[11px] text-warn">Pick up to {MAX_PICK} values, or leave out up to {MAX_PICK}.</p>}
                <div className="mt-2 flex items-center justify-between gap-2 border-t border-line pt-2">
                  <button
                    type="button"
                    disabled={!current}
                    onClick={() => (onApply(null), setOpen(false))}
                    className="text-xs font-semibold text-brand hover:underline disabled:text-ink-subtle disabled:no-underline"
                  >
                    Clear filter
                  </button>
                  <span className="flex gap-1.5">
                    <button type="button" onClick={() => setOpen(false)} className="rounded-lg border border-line px-3 py-1 text-xs hover:bg-muted">
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={apply}
                      disabled={!kept.length || tooMany}
                      className="rounded-lg bg-brand px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
                    >
                      OK
                    </button>
                  </span>
                </div>
              </>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}
