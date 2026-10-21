import { ListChecks, Search, SlidersHorizontal, Star, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { InfoTip } from '@/components/ui/HelpTip';
import { Modal } from '@/components/ui/Overlay';
import { cx, fmtNumber } from '@/lib/format';
import type { DataObject } from '@/types';

type View = 'mine' | 'main' | 'all';
type Kind = 'any' | 'standard' | 'custom';

interface Filters {
  kind: Kind;
  withRecords: boolean;
  showSystem: boolean;
}

const DEFAULT_FILTERS: Filters = { kind: 'any', withRecords: false, showSystem: false };
const MAX_SHOWN = 300; // keep long lists fast; search narrows further

// ---------------------------------------------------------------- browser-only preferences

const KEY = 'aq.data.objects';

interface Prefs {
  mine: string[];
  view: View | null;
  filters: Filters;
}

function loadPrefs(): Prefs {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Partial<Prefs> | null;
    return {
      mine: Array.isArray(raw?.mine) ? raw!.mine.filter((x): x is string => typeof x === 'string') : [],
      view: raw?.view === 'mine' || raw?.view === 'main' || raw?.view === 'all' ? raw.view : null,
      filters: { ...DEFAULT_FILTERS, ...(raw?.filters ?? {}) },
    };
  } catch {
    return { mine: [], view: null, filters: DEFAULT_FILTERS };
  }
}

/** The objects the person picked for "My list" (empty if none). */
export function loadMyList(): string[] {
  return loadPrefs().mine;
}

function savePrefs(p: Prefs) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    // Storage blocked: choices last until the page reloads.
  }
}

// ---------------------------------------------------------------- filtering

function matches(o: DataObject, text: string, f: Filters) {
  if (text) return o.label.toLowerCase().includes(text) || o.labelPlural.toLowerCase().includes(text) || o.name.toLowerCase().includes(text);
  if (!f.showSystem && o.system) return false;
  if (f.kind === 'standard' && o.custom) return false;
  if (f.kind === 'custom' && !o.custom) return false;
  if (f.withRecords && !(o.approxCount && o.approxCount > 0)) return false;
  return true;
}

function FilterControls({ value, onChange }: { value: Filters; onChange: (f: Filters) => void }) {
  return (
    <div className="space-y-2">
      <div className="flex gap-1" role="group" aria-label="Object type">
        {(['any', 'standard', 'custom'] as Kind[]).map((k) => (
          <button
            key={k}
            onClick={() => onChange({ ...value, kind: k })}
            aria-pressed={value.kind === k}
            className={cx(
              'flex-1 rounded-md border px-2 py-1 text-xs font-medium transition',
              value.kind === k ? 'border-brand bg-brand-soft text-brand-ink' : 'border-line text-ink-muted hover:bg-muted',
            )}
          >
            {k === 'any' ? 'Any type' : k === 'standard' ? 'Standard' : 'Custom'}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2 text-xs text-ink-muted">
        <input type="checkbox" checked={value.withRecords} onChange={(e) => onChange({ ...value, withRecords: e.target.checked })} className="accent-[rgb(var(--brand))]" />
        Only objects that have records
      </label>
      <label className="flex items-center gap-2 text-xs text-ink-muted">
        <input type="checkbox" checked={value.showSystem} onChange={(e) => onChange({ ...value, showSystem: e.target.checked })} className="accent-[rgb(var(--brand))]" />
        Show system objects (history, sharing…)
      </label>
    </div>
  );
}

// ---------------------------------------------------------------- chooser

export function ObjectChooser({
  open,
  onClose,
  objects,
  value,
  onSave,
  title = 'Choose your objects',
  description = 'Only the objects you pick will show in “My list”.',
  max = Infinity,
  allowEmpty = true,
}: {
  open: boolean;
  onClose: () => void;
  objects: DataObject[];
  value: string[];
  onSave: (names: string[]) => void;
  title?: string;
  description?: string;
  /** Most objects that can be picked. */
  max?: number;
  allowEmpty?: boolean;
}) {
  const [picked, setPicked] = useState<string[]>(value);
  const [text, setText] = useState('');
  const [filters, setFilters] = useState<Filters>({ ...DEFAULT_FILTERS, withRecords: true });
  useEffect(() => {
    if (open) {
      setPicked(value);
      setText('');
    }
  }, [open, value]);

  const t = text.trim().toLowerCase();
  const list = useMemo(() => objects.filter((o) => matches(o, t, filters)), [objects, t, filters]);
  const byName = useMemo(() => new Map(objects.map((o) => [o.name, o])), [objects]);
  const set = new Set(picked);
  const toggle = (n: string) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : p.length >= max ? p : [...p, n]));
  const shown = list.slice(0, MAX_SHOWN);
  const allShownPicked = shown.length > 0 && shown.every((o) => set.has(o.name));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={max < Infinity ? `${description} Up to ${max}.` : description}
      footer={
        <>
          <Button variant="ghost" onClick={() => setPicked([])} disabled={picked.length === 0}>
            Clear all
          </Button>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!allowEmpty && picked.length === 0}
            onClick={() => {
              onSave(picked);
              onClose();
            }}
          >
            Save {picked.length} {picked.length === 1 ? 'object' : 'objects'}
          </Button>
        </>
      }
    >
      {picked.length > 0 && (
        <div className="mb-3 flex max-h-24 flex-wrap gap-1.5 overflow-y-auto">
          {picked.map((n) => (
            <span key={n} className="inline-flex items-center gap-1 rounded-full bg-brand-soft py-0.5 pl-2.5 pr-1 text-xs font-medium text-brand-ink">
              {byName.get(n)?.labelPlural ?? n}
              <button onClick={() => toggle(n)} className="rounded-full p-0.5 hover:bg-brand/20" aria-label={`Remove ${byName.get(n)?.labelPlural ?? n}`}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <label className="relative mb-3 block">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
        <input className="input pl-9" placeholder="Find an object…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Find an object" />
      </label>
      {!t && (
        <div className="mb-3">
          <FilterControls value={filters} onChange={setFilters} />
        </div>
      )}
      <div className="mb-1 flex items-center justify-between text-xs text-ink-subtle">
        <span>
          {fmtNumber(list.length)} {list.length === 1 ? 'object' : 'objects'}
          {list.length > MAX_SHOWN && ` · showing first ${MAX_SHOWN}, search to narrow`}
        </span>
        {shown.length > 0 && (
          <button
            className="font-medium text-brand hover:underline"
            onClick={() =>
              setPicked((p) =>
                allShownPicked
                  ? p.filter((n) => !shown.some((o) => o.name === n))
                  : [...p, ...shown.map((o) => o.name).filter((n) => !p.includes(n))].slice(0, max),
              )
            }
          >
            {allShownPicked ? 'Unselect these' : 'Select these'}
          </button>
        )}
      </div>
      <ul className="scrollbar-thin max-h-[40vh] space-y-0.5 overflow-y-auto">
        {shown.map((o) => (
          <li key={o.name}>
            <label className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
              <input type="checkbox" checked={set.has(o.name)} onChange={() => toggle(o.name)} className="accent-[rgb(var(--brand))]" />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{o.labelPlural}</span>
                <span className="block truncate font-mono text-[11px] text-ink-subtle">{o.name}</span>
              </span>
              {o.approxCount !== null && <span className="text-[11px] text-ink-subtle">{fmtNumber(o.approxCount)}</span>}
            </label>
          </li>
        ))}
        {shown.length === 0 && <li className="px-2 py-6 text-center text-sm text-ink-subtle">No objects match.</li>}
      </ul>
    </Modal>
  );
}

// ---------------------------------------------------------------- panel

export function ObjectList({ objects, selected }: { objects: DataObject[]; selected?: string }) {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [text, setText] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [chooserOpen, setChooserOpen] = useState(false);

  const update = (p: Partial<Prefs>) =>
    setPrefs((prev) => {
      const next = { ...prev, ...p };
      savePrefs(next);
      return next;
    });

  const available = useMemo(() => new Set(objects.map((o) => o.name)), [objects]);
  const mine = prefs.mine.filter((n) => available.has(n)); // ignore objects this org doesn't have
  const view: View = prefs.view ?? (mine.length ? 'mine' : 'main');
  const f = prefs.filters;
  const activeFilters = (f.kind !== 'any' ? 1 : 0) + (f.withRecords ? 1 : 0) + (f.showSystem ? 1 : 0);

  const t = text.trim().toLowerCase();
  const shown = useMemo(() => {
    const mineSet = new Set(mine);
    return objects.filter((o) => {
      if (view === 'mine' && !mineSet.has(o.name)) return false;
      if (view === 'main' && !o.common && !t) return false;
      // My list and Main are already short, curated lists: filters apply to "All" (and search everywhere).
      return view === 'all' || t ? matches(o, t, f) : true;
    });
  }, [objects, mine, view, t, f]);

  const counts = { mine: mine.length, main: objects.filter((o) => o.common).length, all: objects.filter((o) => matches(o, '', f)).length };
  const toggleMine = (name: string) => update({ mine: mine.includes(name) ? mine.filter((n) => n !== name) : [...mine, name] });

  return (
    <section className="card flex min-h-0 flex-col lg:sticky lg:top-20 lg:max-h-[calc(100vh-7rem)]">
      <div className="space-y-3 border-b border-line p-4">
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          Objects
          <InfoTip>Each object is a kind of record in Salesforce, like Accounts or Leads. Star the ones you use to build “My list”.</InfoTip>
          <span className="ml-auto text-xs font-normal text-ink-subtle">{fmtNumber(objects.length)} available</span>
        </div>
        <label className="relative block">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
          <input className="input pl-9" placeholder="Find an object…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Find an object" />
        </label>
        <div className="flex gap-1" role="group" aria-label="Which objects to list">
          {(['mine', 'main', 'all'] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => update({ view: v })}
              aria-pressed={view === v}
              className={cx('flex-1 rounded-md px-2 py-1 text-xs font-medium transition', view === v ? 'bg-brand-soft text-brand-ink' : 'text-ink-muted hover:bg-muted')}
            >
              {v === 'mine' ? 'My list' : v === 'main' ? 'Main' : 'All'} <span className="opacity-70">{fmtNumber(counts[v])}</span>
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <Button size="sm" className="flex-1" icon={<ListChecks className="h-3.5 w-3.5" />} onClick={() => setChooserOpen(true)}>
            Choose objects
          </Button>
          {view === 'all' && (
            <Button
              size="sm"
              variant={showFilters || activeFilters ? 'subtle' : 'secondary'}
              icon={<SlidersHorizontal className="h-3.5 w-3.5" />}
              onClick={() => setShowFilters((s) => !s)}
              aria-expanded={showFilters}
            >
              Filter{activeFilters ? ` (${activeFilters})` : ''}
            </Button>
          )}
        </div>
        {view === 'all' && showFilters && <FilterControls value={f} onChange={(filters) => update({ filters })} />}
      </div>

      <ul className="scrollbar-thin max-h-[50vh] min-h-0 flex-1 overflow-y-auto p-2 lg:max-h-none">
        {shown.length === 0 &&
          (view === 'mine' && !t ? (
            <li className="px-3 py-6 text-center text-sm text-ink-subtle">
              Your list is empty.
              <br />
              <button className="mt-1 font-medium text-brand hover:underline" onClick={() => setChooserOpen(true)}>
                Choose objects
              </button>{' '}
              or star them in Main / All.
            </li>
          ) : (
            <li className="px-3 py-6 text-center text-sm text-ink-subtle">No objects match.</li>
          ))}
        {shown.slice(0, MAX_SHOWN).map((o) => {
          const starred = mine.includes(o.name);
          return (
            <li key={o.name} className="group flex items-center gap-1">
              <Link
                to={`/data/${encodeURIComponent(o.name)}`}
                aria-current={o.name === selected ? 'page' : undefined}
                className={cx('flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-2 text-sm transition', o.name === selected ? 'bg-brand-soft text-brand-ink' : 'hover:bg-muted')}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{o.labelPlural}</span>
                  <span className="block truncate font-mono text-[11px] text-ink-subtle">{o.name}</span>
                </span>
                {o.approxCount !== null && <span className="shrink-0 rounded-full bg-muted px-2 text-[11px] text-ink-muted">{fmtNumber(o.approxCount)}</span>}
              </Link>
              <button
                onClick={() => toggleMine(o.name)}
                aria-pressed={starred}
                aria-label={starred ? `Remove ${o.labelPlural} from My list` : `Add ${o.labelPlural} to My list`}
                title={starred ? 'Remove from My list' : 'Add to My list'}
                className={cx(
                  'shrink-0 rounded-md p-1.5 transition hover:bg-muted',
                  starred ? 'text-warn' : 'text-ink-subtle opacity-40 group-hover:opacity-100 focus-visible:opacity-100',
                )}
              >
                <Star className="h-4 w-4" fill={starred ? 'currentColor' : 'none'} />
              </button>
            </li>
          );
        })}
        {shown.length > MAX_SHOWN && (
          <li className="px-3 py-3 text-center text-xs text-ink-subtle">
            Showing {MAX_SHOWN} of {fmtNumber(shown.length)}. Search or filter to narrow down.
          </li>
        )}
      </ul>

      <ObjectChooser open={chooserOpen} onClose={() => setChooserOpen(false)} objects={objects} value={mine} onSave={(names) => update({ mine: names, view: 'mine' })} />
    </section>
  );
}
