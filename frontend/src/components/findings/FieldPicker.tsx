import { ChevronDown, Search } from 'lucide-react';
import { useState } from 'react';
import { useDataObject } from '@/api/queries';
import { Button } from '@/components/ui/Button';
import { cx } from '@/lib/format';

export const MAX_SHOWN = 10;

/** Pick the fields a records table shows as its columns (Area 1's "Fields to check" list, for showing instead of checking).
 *  `current` = the columns shown now (the measure's own until fields are picked); `onChange(null)` goes back to those. */
export function FieldPicker({
  object,
  current,
  picked,
  onChange,
}: {
  object: string;
  current: string[];
  picked: string[] | null;
  onChange: (fields: string[] | null) => void;
}) {
  const describe = useDataObject(object);
  const fields = (describe.data?.fields ?? []).filter((f) => f.column && f.type !== 'id');
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const label = (name: string) => fields.find((f) => f.name === name)?.label ?? name;
  const shown = picked ?? current.filter((c) => fields.some((f) => f.name === c));
  const toggle = () => {
    if (!open) setDraft(shown.slice(0, MAX_SHOWN));
    setQuery('');
    setOpen((o) => !o);
  };
  // The ticked fields first, in the order they were picked, so they're seen without scrolling.
  const list = [...draft.flatMap((n) => fields.filter((f) => f.name === n)), ...fields.filter((f) => !draft.includes(f.name))].filter(
    (f) => !query || `${f.label} ${f.name}`.toLowerCase().includes(query.toLowerCase()),
  );
  const same = draft.length === shown.length && draft.every((f, i) => f === shown[i]);

  return (
    <div className="rounded-lg border border-line p-3">
      <div className={cx('flex flex-wrap items-center gap-3', open && 'mb-3')}>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="group flex min-w-0 flex-1 items-center gap-2 text-left text-sm"
          title={open ? 'Hide the field list' : 'Choose the fields shown in the table'}
        >
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md border border-line bg-surface text-ink-muted transition group-hover:border-brand/40 group-hover:text-brand">
            <ChevronDown className={cx('h-4 w-4 transition-transform', !open && '-rotate-90')} />
          </span>
          Fields to show <span className="text-ink-muted">({open ? draft.length : shown.length}/{MAX_SHOWN} chosen)</span>
          {!open && <span className="text-xs font-medium text-brand group-hover:underline">Change</span>}
        </button>
        {open && (
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
            <input className="input h-8 w-56 pl-8 text-xs" placeholder="Filter fields…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        )}
      </div>
      {!open && (
        <p className="mt-2 pl-8 text-xs text-ink-muted">
          Showing: <span className="font-medium text-ink">{shown.map(label).join(', ') || '—'}</span>
          {picked && (
            <button type="button" className="ml-2 text-brand hover:underline" onClick={() => onChange(null)}>
              Back to the usual fields
            </button>
          )}
        </p>
      )}
      {open &&
        (describe.isLoading ? (
          <p className="text-xs text-ink-subtle">Reading this object’s fields…</p>
        ) : (
          <>
            <div className="scrollbar-thin grid max-h-64 gap-1.5 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
              {list.map((f) => {
                const on = draft.includes(f.name);
                const full = !on && draft.length >= MAX_SHOWN;
                return (
                  <label
                    key={f.name}
                    className={cx(
                      'flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm transition',
                      on ? 'border-brand bg-brand-soft/60' : 'border-line hover:border-brand/30',
                      full && 'cursor-not-allowed opacity-50',
                    )}
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 accent-[rgb(var(--brand))]"
                      checked={on}
                      disabled={full}
                      onChange={(e) => setDraft(e.target.checked ? [...draft, f.name] : draft.filter((x) => x !== f.name))}
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{f.label}</span>
                      <span className="block truncate text-[11px] text-ink-subtle">{f.name} · {f.type}</span>
                    </span>
                  </label>
                );
              })}
              {list.length === 0 && <p className="text-xs text-ink-subtle">No fields match “{query}”.</p>}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="primary"
                disabled={!draft.length || same}
                onClick={() => {
                  onChange(draft);
                  setOpen(false);
                }}
              >
                Show {draft.length} field{draft.length === 1 ? '' : 's'}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              {draft.length > 0 && (
                <button type="button" className="text-xs text-brand hover:underline" onClick={() => setDraft([])}>
                  Clear
                </button>
              )}
            </div>
          </>
        ))}
    </div>
  );
}
