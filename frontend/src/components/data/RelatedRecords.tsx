import { ChevronDown, ChevronRight, ExternalLink, Link2, Search } from 'lucide-react';
import { useState } from 'react';
import { useDataRelated } from '@/api/queries';
import { formatValue } from '@/components/data/format';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { cx, fmtNumber } from '@/lib/format';
import type { DataChildRelationship, DataField, DataObjectDetail } from '@/types';

const SHOWN_CHIPS = 8;
const MAX_MATCHES = 40;
const prefKey = (obj: string) => `aq.data.related.${obj}`;

/** Remembered related-list choice for an object (default: its two most common lists, e.g. Contacts and Opportunities). */
function loadChoice(obj: string, rels: DataChildRelationship[]): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(prefKey(obj)) ?? 'null') as unknown;
    if (Array.isArray(v)) return v.filter((n): n is string => typeof n === 'string' && rels.some((r) => r.name === n));
  } catch {
    // Storage blocked: fall back to the defaults.
  }
  // Default: the standard list of the two most common related objects (e.g. Contacts and Opportunities).
  const firstPerObject = rels.filter((r, i) => rels.findIndex((x) => x.object === r.object) === i);
  return firstPerObject.slice(0, 2).map((r) => r.name);
}

function saveChoice(obj: string, names: string[]) {
  try {
    localStorage.setItem(prefKey(obj), JSON.stringify(names));
  } catch {
    // The choice just won't be remembered.
  }
}

/**
 * The "Related" part of a record panel: pick which related lists to see (e.g. Contacts, Opportunities, or both),
 * each with a count and its records. Clicking a related record opens it.
 */
export function RelatedRecords({
  detail,
  recordId,
  onOpen,
}: {
  detail: DataObjectDetail;
  recordId: string;
  onOpen: (object: string, id: string) => void;
}) {
  const rels = detail.childRelationships ?? [];
  const [chosen, setChosen] = useState<string[]>(() => loadChoice(detail.name, rels));
  const [showAll, setShowAll] = useState(false);
  const [find, setFind] = useState('');

  if (rels.length === 0) {
    return <EmptyState className="py-10" icon={<Link2 className="h-6 w-6" />} title="No related lists" description={`${detail.labelPlural} have no related records you can see.`} />;
  }

  const toggle = (name: string) => {
    const next = chosen.includes(name) ? chosen.filter((n) => n !== name) : [...chosen, name];
    setChosen(next);
    saveChoice(detail.name, next);
  };
  const term = find.trim().toLowerCase();
  const matches = term ? rels.filter((r) => r.label.toLowerCase().includes(term) || r.object.toLowerCase().includes(term)) : rels;
  // Chosen lists always stay visible as chips, so they can be switched off.
  const visible = showAll
    ? matches.slice(0, MAX_MATCHES)
    : [...rels.slice(0, SHOWN_CHIPS), ...rels.slice(SHOWN_CHIPS).filter((r) => chosen.includes(r.name))];
  // Keep the lists in the same order as the chips.
  const selected = rels.filter((r) => chosen.includes(r.name));

  return (
    <div>
      <p className="mb-2 text-xs font-medium text-ink-muted">Show related</p>
      {showAll && (
        <label className="relative mb-2 block">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
          <input className="input h-8 pl-9 text-xs" placeholder={`Find among ${rels.length} related lists…`} value={find} onChange={(e) => setFind(e.target.value)} autoFocus aria-label="Find a related list" />
        </label>
      )}
      <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Related lists to show">
        {visible.map((r) => {
          const on = chosen.includes(r.name);
          return (
            <button
              key={r.name}
              onClick={() => toggle(r.name)}
              aria-pressed={on}
              className={cx(
                'rounded-full border px-3 py-1 text-xs font-medium transition',
                on ? 'border-brand bg-brand-soft text-brand-ink' : 'border-line text-ink-muted hover:border-ink-subtle/40 hover:text-ink',
              )}
              title={`${r.label} (linked by ${r.field})`}
            >
              {r.label}
            </button>
          );
        })}
        {rels.length > SHOWN_CHIPS && (
          <button onClick={() => setShowAll((v) => !v)} className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium text-brand hover:underline">
            {showAll ? 'Fewer' : `${fmtNumber(rels.length - SHOWN_CHIPS)} more`}
            <ChevronDown className={cx('h-3 w-3 transition', showAll && 'rotate-180')} />
          </button>
        )}
      </div>

      {showAll && matches.length > MAX_MATCHES && (
        <p className="-mt-2 mb-3 text-[11px] text-ink-subtle">Showing {MAX_MATCHES} of {fmtNumber(matches.length)}. Type to narrow down.</p>
      )}
      {selected.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-ink-subtle">Pick one or more related lists above.</p>
      ) : (
        <div className="space-y-4">
          {selected.map((r) => (
            <RelatedList key={r.name} parent={detail.name} recordId={recordId} rel={r} onOpen={onOpen} />
          ))}
        </div>
      )}
    </div>
  );
}

function RelatedList({
  parent,
  recordId,
  rel,
  onOpen,
}: {
  parent: string;
  recordId: string;
  rel: DataChildRelationship;
  onOpen: (object: string, id: string) => void;
}) {
  const q = useDataRelated(parent, recordId, rel.name);
  const page = q.data;
  const detailCols = page ? page.columns.filter((c) => c.type !== 'id' && c.name !== page.nameField).slice(0, 2) : [];
  const asField = (c: { name: string; label: string; type: string }) => ({ ...c }) as unknown as DataField;

  return (
    <section className="overflow-hidden rounded-xl border border-line">
      <header className="flex items-center gap-2 border-b border-line bg-muted/50 px-3 py-2">
        <span className="text-sm font-semibold">{rel.label}</span>
        {page?.totalSize != null && <span className="rounded-full bg-surface px-2 text-[11px] tabular-nums text-ink-muted">{fmtNumber(page.totalSize)}</span>}
        {page?.salesforceUrl && (
          <a href={page.salesforceUrl} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-brand hover:underline">
            Open in Salesforce <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </header>
      {q.isLoading ? (
        <LoadingState rows={3} label={`Loading ${rel.label}…`} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} className="py-6" />
      ) : !page || page.records.length === 0 ? (
        <p className="px-3 py-4 text-center text-xs text-ink-subtle">No {rel.label.toLowerCase()} yet.</p>
      ) : (
        <>
          <ul className="divide-y divide-line">
            {page.records.map((r, i) => {
              const title = page.nameField ? r.values[page.nameField] : null;
              return (
                <li key={r.id ?? i}>
                  <button onClick={() => r.id && onOpen(page.object, r.id)} className="group flex w-full items-center gap-3 px-3 py-2 text-left transition hover:bg-muted">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium group-hover:text-brand">{typeof title === 'string' && title ? title : r.id}</span>
                      {detailCols.length > 0 && (
                        <span className="block truncate text-xs text-ink-subtle">
                          {detailCols
                            .map((c) => formatValue(asField(c), r.values[c.name], r.refNames[c.name]))
                            .filter((t) => t !== '—')
                            .join(' · ') || '—'}
                        </span>
                      )}
                    </span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-ink-subtle transition group-hover:translate-x-0.5" />
                  </button>
                </li>
              );
            })}
          </ul>
          {page.totalSize != null && page.totalSize > page.records.length && (
            <p className="border-t border-line px-3 py-2 text-center text-[11px] text-ink-subtle">
              Showing {page.records.length} of {fmtNumber(page.totalSize)} — open in Salesforce to see all.
            </p>
          )}
        </>
      )}
    </section>
  );
}
