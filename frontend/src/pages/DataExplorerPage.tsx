import {
  ArrowDown,
  ArrowUp,
  Columns3,
  Database,
  ExternalLink,
  Eye,
  EyeOff,
  Link2,
  ListTree,
  RefreshCw,
  Rows3,
  Search,
  Sparkles,
  Unplug,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useConnection, useDataObject, useDataObjects, useDataRecord, useDataRecords, useRefreshData } from '@/api/queries';
import { formatValue, typeLabel } from '@/components/data/format';
import { ObjectList } from '@/components/data/ObjectList';
import { FindOrAsk } from '@/components/data/FindOrAsk';
import { RelatedRecords } from '@/components/data/RelatedRecords';
import { Button, LinkButton } from '@/components/ui/Button';
import { InfoTip } from '@/components/ui/HelpTip';
import { Drawer, Modal } from '@/components/ui/Overlay';
import { PageHeader } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { Tabs } from '@/components/ui/Tabs';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, DataFilter, DataObjectDetail } from '@/types';

type Tab = 'records' | 'fields';

const MAX_COLUMNS = 25;

// ---------------------------------------------------------------- helpers

function useDebounced<T>(value: T, ms = 400) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Remember chosen columns per object in this browser (a convenience only). */
const colsKey = (obj: string) => `aq.data.columns.${obj}`;
function loadCols(obj: string): string[] | null {
  try {
    const raw = localStorage.getItem(colsKey(obj));
    const v = raw ? (JSON.parse(raw) as unknown) : null;
    return Array.isArray(v) && v.every((x) => typeof x === 'string') ? (v as string[]) : null;
  } catch {
    return null;
  }
}
function saveCols(obj: string, cols: string[] | null) {
  try {
    if (cols) localStorage.setItem(colsKey(obj), JSON.stringify(cols));
    else localStorage.removeItem(colsKey(obj));
  } catch {
    // Storage blocked: columns just won't be remembered.
  }
}

// ---------------------------------------------------------------- column picker

function ColumnPicker({
  open,
  onClose,
  detail,
  value,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  detail: DataObjectDetail;
  value: string[];
  onApply: (cols: string[] | null) => void;
}) {
  const [picked, setPicked] = useState<string[]>(value);
  const [text, setText] = useState('');
  useEffect(() => {
    if (open) {
      setPicked(value);
      setText('');
    }
  }, [open, value]);

  const t = text.trim().toLowerCase();
  const options = detail.fields.filter((f) => f.column && (!t || f.label.toLowerCase().includes(t) || f.name.toLowerCase().includes(t)));
  const toggle = (name: string) =>
    setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : p.length >= MAX_COLUMNS ? p : [...p, name]));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Choose columns"
      description={`Pick up to ${MAX_COLUMNS} fields to show in the table.`}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={() => {
              onApply(null);
              onClose();
            }}
          >
            Reset to default
          </Button>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={picked.length === 0}
            onClick={() => {
              onApply(picked);
              onClose();
            }}
          >
            Show {picked.length} columns
          </Button>
        </>
      }
    >
      <label className="relative mb-3 block">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
        <input className="input pl-9" placeholder="Find a field…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Find a field" />
      </label>
      <ul className="scrollbar-thin max-h-[50vh] space-y-0.5 overflow-y-auto">
        {options.map((f) => {
          const on = picked.includes(f.name);
          return (
            <li key={f.name}>
              <label className={cx('flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-muted', !on && picked.length >= MAX_COLUMNS && 'opacity-50')}>
                <input type="checkbox" checked={on} onChange={() => toggle(f.name)} className="accent-[rgb(var(--brand))]" />
                <span className="min-w-0 flex-1 truncate">{f.label}</span>
                <span className="truncate font-mono text-[11px] text-ink-subtle">{f.name}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </Modal>
  );
}

// ---------------------------------------------------------------- record panel

function RecordPanel({ detail, id, onClose }: { detail: DataObjectDetail; id: string | null; onClose: () => void }) {
  const rec = useDataRecord(detail.name, id);
  const navigate = useNavigate();
  const [showEmpty, setShowEmpty] = useState(false);
  const [view, setView] = useState<'details' | 'related'>('details');
  const name = rec.data && detail.nameField ? rec.data.values[detail.nameField] : null;
  const relCount = detail.childRelationships?.length ?? 0;

  return (
    <Drawer
      open={!!id}
      onClose={onClose}
      title={typeof name === 'string' && name ? name : detail.label}
      subtitle={<span className="font-mono text-xs text-ink-subtle">{id}</span>}
      footer={
        rec.data && (
          <a href={rec.data.salesforceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand px-4 text-sm font-medium text-white hover:brightness-110">
            Open in Salesforce <ExternalLink className="h-4 w-4" />
          </a>
        )
      }
    >
      {rec.isLoading ? (
        <LoadingState rows={8} label="Loading record…" />
      ) : rec.error ? (
        <ErrorState error={rec.error} onRetry={() => rec.refetch()} />
      ) : (
        rec.data && (
          <>
            {relCount > 0 && (
              <div className="mb-4">
                <Tabs<'details' | 'related'>
                  layoutId="record-panel-tabs"
                  value={view}
                  onChange={setView}
                  tabs={[
                    { id: 'details', label: 'Details' },
                    { id: 'related', label: 'Related', count: relCount },
                  ]}
                />
              </div>
            )}
            {view === 'related' && relCount > 0 ? (
              <RelatedRecords
                detail={detail}
                recordId={id!}
                onOpen={(object, childId) =>
                  navigate(`/data/${encodeURIComponent(object)}?only=${encodeURIComponent(childId)}`, {
                    state: { from: `related to ${typeof name === 'string' && name ? `${name} (${detail.label})` : detail.label}` },
                  })
                }
              />
            ) : (
            <>
            <button onClick={() => setShowEmpty((v) => !v)} className="mb-3 inline-flex items-center gap-1.5 text-xs font-medium text-brand hover:underline">
              {showEmpty ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              {showEmpty ? 'Hide empty fields' : 'Show empty fields'}
            </button>
            <dl className="divide-y divide-line">
              {detail.fields
                .filter((f) => showEmpty || !['', null, undefined].includes(rec.data!.values[f.name] as never))
                .map((f) => (
                  <div key={f.name} className="grid grid-cols-[minmax(0,2fr),minmax(0,3fr)] gap-3 py-2">
                    <dt className="min-w-0">
                      <span className="block truncate text-xs font-medium text-ink-muted">{f.label}</span>
                      <span className="block truncate font-mono text-[10px] text-ink-subtle">{f.name}</span>
                    </dt>
                    <dd className="min-w-0 whitespace-pre-wrap break-words text-sm">
                      {formatValue(f, rec.data!.values[f.name], rec.data!.refNames[f.name])}
                    </dd>
                  </div>
                ))}
            </dl>
            </>
            )}
          </>
        )
      )}
    </Drawer>
  );
}

// ---------------------------------------------------------------- records tab

function parseFilters(raw: string | null): DataFilter[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw) as unknown;
    return Array.isArray(v)
      ? v.filter((f): f is DataFilter => !!f && typeof f === 'object' && typeof (f as DataFilter).field === 'string' && typeof (f as DataFilter).op === 'string').slice(0, 20)
      : [];
  } catch {
    return [];
  }
}

/** The answer to a question: how many records match, and the filters applied (each removable). */
function AnswerBanner({
  question,
  total,
  loading,
  labelPlural,
  filters,
  ignored,
  onRemove,
  onClear,
}: {
  question: string | null;
  total: number | null;
  loading: boolean;
  labelPlural: string;
  filters: DataFilter[];
  ignored: string[];
  onRemove: (index: number) => void;
  onClear: () => void;
}) {
  return (
    <div className="mx-4 mt-4 rounded-xl border border-brand/30 bg-brand-soft/60 p-3">
      <div className="flex flex-wrap items-start gap-3">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        <div className="min-w-0 flex-1">
          {question && <p className="truncate text-xs text-ink-muted">“{question}”</p>}
          <p className="text-sm">
            <span className="text-xl font-semibold tabular-nums text-brand-ink">{loading || total === null ? '…' : fmtNumber(total)}</span>{' '}
            <span className="font-medium">{labelPlural.toLowerCase()} match</span>
          </p>
        </div>
        <button onClick={onClear} className="text-xs font-semibold text-brand hover:underline">
          Clear
        </button>
      </div>
      {filters.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 pl-7">
          {filters.map((f, i) => (
            <span key={`${f.field}-${f.op}-${i}`} className="inline-flex items-center gap-1 rounded-full border border-brand/30 bg-surface px-2.5 py-0.5 text-xs">
              {f.label ?? `${f.field} ${f.op} ${String(f.value ?? '')}`}
              <button onClick={() => onRemove(i)} className="rounded-full text-ink-subtle hover:text-bad" aria-label={`Remove filter ${f.label ?? f.field}`}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      {ignored.length > 0 && (
        <p className="mt-2 pl-7 text-[11px] text-ink-subtle">
          Not understood, so not applied: {ignored.map((w) => `“${w}”`).join(', ')}
        </p>
      )}
    </div>
  );
}

function RecordsTab({ detail }: { detail: DataObjectDetail }) {
  const [custom, setCustom] = useState<string[] | null>(() => loadCols(detail.name));
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<{ field: string; dir: 'asc' | 'desc' } | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  // The open record lives in the URL (?record=…), so related records can link to each other and Back works.
  const [params, setParams] = useSearchParams();
  const openId = params.get('record');
  // Opened from a related list: show only that record until the user asks for all.
  const only = params.get('only');
  const from = (useLocation().state as { from?: string } | null)?.from;
  const showAll = () =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      n.delete('only');
      return n;
    });
  // Filters from a question ("open deals over 50k") live in the URL too, so answers can be shared and Back works.
  const question = params.get('ask');
  const filters = useMemo(() => parseFilters(params.get('f')), [params]);
  const ignored = (params.get('ig') ?? '').split(',').filter(Boolean);
  const setFilters = (next: DataFilter[] | null) =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      if (next && next.length) n.set('f', JSON.stringify(next));
      else ['f', 'ask', 'ig', 'sort', 'dir'].forEach((k) => n.delete(k));
      return n;
    });
  const urlSort = params.get('sort');
  const urlDir = params.get('dir') === 'asc' ? 'asc' : 'desc';
  useEffect(() => {
    if (urlSort) setSort({ field: urlSort, dir: urlDir });
  }, [urlSort, urlDir]);
  const setOpenId = (id: string | null) =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      if (id) n.set('record', id);
      else n.delete('record');
      return n;
    });
  const q = useDebounced(search);

  const fieldMap = useMemo(() => new Map(detail.fields.map((f) => [f.name, f])), [detail.fields]);
  const columns = (custom ?? detail.defaultColumns).filter((c) => fieldMap.has(c));
  const query = { fields: custom ?? undefined, q: q || undefined, sort: sort?.field, dir: sort?.dir, ids: only ? [only] : undefined, filters: filters.length ? filters : undefined };
  const recs = useDataRecords(detail.name, query);

  const rows = recs.data?.pages.flatMap((p) => p.records) ?? [];
  const shownCols = recs.data?.pages[0]?.columns.filter((c) => fieldMap.has(c)) ?? columns;
  const total = recs.data?.pages[0]?.totalSize ?? null;

  const onSort = (f: DataField) => {
    if (!f.sortable) return;
    setSort((s) => (s?.field === f.name ? { field: f.name, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { field: f.name, dir: 'asc' }));
  };

  return (
    <div>
      {only && (
        <div className="mx-4 mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-brand/30 bg-brand-soft px-3 py-2 text-sm text-brand-ink">
          <Link2 className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">
            Showing only this {detail.label.toLowerCase()}
            {from && <span className="font-semibold"> — {from}</span>}
          </span>
          <button onClick={showAll} className="inline-flex items-center gap-1 text-xs font-semibold text-brand hover:underline">
            Show all {detail.labelPlural} <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      {(filters.length > 0 || question) && (
        <AnswerBanner
          question={question}
          total={total}
          loading={recs.isLoading}
          labelPlural={detail.labelPlural}
          filters={filters}
          ignored={ignored}
          onRemove={(i) => setFilters(filters.filter((_, j) => j !== i))}
          onClear={() => setFilters(null)}
        />
      )}
      <div className="flex flex-wrap items-center gap-2 p-4">
        {detail.searchable ? (
          <label className="relative min-w-[200px] flex-1 sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
            <input
              className="input pl-9"
              placeholder={`Search by ${fieldMap.get(detail.nameField!)?.label ?? 'name'}…`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search records"
            />
          </label>
        ) : (
          <span className="text-xs text-ink-subtle">This object can’t be searched by name.</span>
        )}
        <span className="text-xs text-ink-muted">
          {total !== null && `${fmtNumber(rows.length)} of ${fmtNumber(total)} records`}
          {recs.isFetching && !recs.isFetchingNextPage && ' · updating…'}
        </span>
        <Button size="sm" className="ml-auto" icon={<Columns3 className="h-3.5 w-3.5" />} onClick={() => setPickerOpen(true)}>
          Columns
        </Button>
      </div>

      {recs.isLoading ? (
        <LoadingState rows={6} label="Loading records…" />
      ) : recs.error ? (
        <ErrorState error={recs.error} onRetry={() => recs.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={q || filters.length ? 'No records match' : 'No records yet'}
          description={filters.length ? 'Try removing a filter above.' : q ? 'Try a different name.' : `There are no ${detail.labelPlural} you can see.`}
        />
      ) : (
        <>
          <div className="scrollbar-thin relative overflow-x-auto border-t border-line">
            <table className="w-full border-collapse">
              <thead className="bg-muted/50">
                <tr>
                  {shownCols.map((c) => {
                    const f = fieldMap.get(c)!;
                    const active = sort?.field === c;
                    return (
                      <th key={c} className="th" aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : undefined}>
                        {f.sortable ? (
                          <button onClick={() => onSort(f)} className={cx('inline-flex items-center gap-1 uppercase tracking-wide hover:text-ink', active && 'text-ink')} title={f.name}>
                            {f.label}
                            {active && (sort!.dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                          </button>
                        ) : (
                          <span title={f.name}>{f.label}</span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr
                    key={r.id ?? i}
                    onClick={() => r.id && setOpenId(r.id)}
                    onKeyDown={(e) => e.key === 'Enter' && r.id && setOpenId(r.id)}
                    tabIndex={0}
                    className="cursor-pointer border-t border-line transition hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
                  >
                    {shownCols.map((c) => {
                      const f = fieldMap.get(c)!;
                      const text = formatValue(f, r.values[c], r.refNames[c]);
                      return (
                        <td key={c} className={cx('td max-w-[260px] truncate', (f.type === 'id' || (f.type === 'reference' && !r.refNames[c])) && 'font-mono text-xs', ['currency', 'double', 'int', 'percent'].includes(f.type) && 'text-right tabular-nums')} title={text}>
                          {text}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {recs.hasNextPage && (
            <div className="flex justify-center border-t border-line p-4">
              <Button onClick={() => recs.fetchNextPage()} disabled={recs.isFetchingNextPage}>
                {recs.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </>
      )}

      <ColumnPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        detail={detail}
        value={columns}
        onApply={(cols) => {
          setCustom(cols);
          saveCols(detail.name, cols);
        }}
      />
      <RecordPanel key={openId ?? 'none'} detail={detail} id={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

// ---------------------------------------------------------------- fields tab

function FieldsTab({ detail }: { detail: DataObjectDetail }) {
  const [text, setText] = useState('');
  const t = text.trim().toLowerCase();
  const fields = detail.fields.filter((f) => !t || f.label.toLowerCase().includes(t) || f.name.toLowerCase().includes(t));
  return (
    <div>
      <div className="p-4">
        <label className="relative block sm:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
          <input className="input pl-9" placeholder="Find a field…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Find a field" />
        </label>
      </div>
      <div className="scrollbar-thin relative overflow-x-auto border-t border-line">
        <table className="w-full min-w-[640px] border-collapse">
          <thead className="bg-muted/50">
            <tr>
              <th className="th">Field</th>
              <th className="th">API name</th>
              <th className="th">Type</th>
              <th className="th">Notes</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => (
              <tr key={f.name} className="border-t border-line">
                <td className="td">
                  <span className="inline-flex items-center gap-1.5">
                    {f.label}
                    {f.helpText && <InfoTip label={`About ${f.label}`}>{f.helpText}</InfoTip>}
                  </span>
                </td>
                <td className="td font-mono text-xs text-ink-muted">{f.name}</td>
                <td className="td text-ink-muted">
                  {typeLabel(f)}
                  {f.picklistValues.length > 0 && (
                    <InfoTip label={`Options for ${f.label}`}>
                      {f.picklistValues.slice(0, 30).join(', ')}
                      {f.picklistValues.length > 30 && ` … and ${f.picklistValues.length - 30} more`}
                    </InfoTip>
                  )}
                </td>
                <td className="td">
                  <span className="flex flex-wrap gap-1">
                    {f.required && <span className="rounded-full bg-warn-soft px-2 text-[11px] font-medium text-warn">Required</span>}
                    {f.custom && <span className="rounded-full bg-brand-soft px-2 text-[11px] font-medium text-brand-ink">Custom</span>}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {fields.length === 0 && <p className="px-4 py-8 text-center text-sm text-ink-subtle">No fields match.</p>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- object view

function ObjectView({ name }: { name: string }) {
  const detail = useDataObject(name);
  const refresh = useRefreshData();
  const [tab, setTab] = useState<Tab>('records');
  useEffect(() => setTab('records'), [name]);

  if (detail.isLoading) {
    return (
      <div className="card">
        <LoadingState rows={6} label="Loading object…" />
      </div>
    );
  }
  if (detail.error || !detail.data) {
    return (
      <div className="card">
        <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
      </div>
    );
  }
  const d = detail.data;
  return (
    <section className="card min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
        <div className="min-w-0">
          <h2 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
            {d.labelPlural}
            {d.custom && <span className="rounded-full bg-brand-soft px-2 text-[11px] font-medium text-brand-ink">Custom</span>}
          </h2>
          <p className="mt-0.5 text-xs text-ink-subtle">
            <span className="font-mono">{d.name}</span>
            {d.approxCount !== null && ` · about ${fmtNumber(d.approxCount)} records`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" icon={<RefreshCw className={cx('h-3.5 w-3.5', refresh.isPending && 'animate-spin')} />} onClick={() => refresh.mutate()} disabled={refresh.isPending}>
            Refresh
          </Button>
          {d.salesforceUrl && (
            <a href={d.salesforceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-xs font-medium hover:bg-muted">
              Open in Salesforce <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </div>
      <div className="mt-3 px-5">
        <Tabs<Tab>
          layoutId="data-tabs"
          value={tab}
          onChange={setTab}
          tabs={[
            { id: 'records', label: 'Records', icon: <Rows3 className="h-4 w-4" /> },
            { id: 'fields', label: 'Fields', icon: <ListTree className="h-4 w-4" />, count: d.fields.length },
          ]}
        />
      </div>
      {tab === 'records' ? <RecordsTab key={d.name} detail={d} /> : <FieldsTab detail={d} />}
    </section>
  );
}

// ---------------------------------------------------------------- page

export default function DataExplorerPage() {
  const { objectName } = useParams();
  const navigate = useNavigate();
  const conn = useConnection();
  const connected = conn.data?.status === 'connected';
  const objects = useDataObjects(connected);

  // Open Accounts (or the first object) when no object is chosen yet.
  useEffect(() => {
    if (!objectName && objects.data?.length) {
      const first = objects.data.find((o) => o.name === 'Account') ?? objects.data[0];
      navigate(`/data/${encodeURIComponent(first.name)}`, { replace: true });
    }
  }, [objectName, objects.data, navigate]);

  const header = (
    <PageHeader
      title="Your Data"
      description="See what’s in your Salesforce: every object, its fields, and its records. Read-only — nothing can be changed here."
    />
  );

  if (conn.isLoading) {
    return (
      <div>
        {header}
        <div className="card">
          <LoadingState rows={4} />
        </div>
      </div>
    );
  }
  if (!connected) {
    const expired = conn.data?.status === 'expired';
    return (
      <div>
        {header}
        <div className="card">
          <EmptyState
            icon={<Unplug className="h-6 w-6" />}
            title={expired ? 'Your Salesforce connection has timed out' : 'Connect Salesforce to see your data'}
            description={expired ? 'Reconnect to keep browsing your data.' : 'Once connected, every object and record you can see in Salesforce shows up here.'}
            action={
              <LinkButton to="/connection" variant="primary" icon={<Link2 className="h-4 w-4" />}>
                {expired ? 'Reconnect' : 'Connect Salesforce'}
              </LinkButton>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div>
      {header}
      {objects.isLoading ? (
        <div className="card">
          <LoadingState rows={6} label="Loading objects…" />
        </div>
      ) : objects.error ? (
        <div className="card">
          <ErrorState error={objects.error} onRetry={() => objects.refetch()} />
        </div>
      ) : objects.data && objects.data.length === 0 ? (
        <div className="card">
          <EmptyState icon={<Database className="h-6 w-6" />} title="No objects available" description="Your Salesforce user can’t read any objects. Ask your admin to check your permissions." />
        </div>
      ) : (
        <>
        <FindOrAsk current={objectName} />
        <div className="grid items-start gap-6 lg:grid-cols-[280px,minmax(0,1fr)]">
          <ObjectList objects={objects.data ?? []} selected={objectName} />
          {objectName ? <ObjectView key={objectName} name={objectName} /> : <div className="card"><LoadingState rows={4} /></div>}
        </div>
        </>
      )}
    </div>
  );
}
