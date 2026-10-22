import { ChevronRight, Download, ExternalLink, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { errorMessage } from '@/api/client';
import { dataApi } from '@/api/endpoints';
import { useEmptyOptions } from '@/api/queries';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { formatValue } from '@/components/data/format';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, EmptyResult } from '@/types';
import { Button } from '../ui/Button';
import { LoadingState } from '../ui/States';
import { AnimatedNumber } from '../ui/Visuals';

const MAX_FIELDS = 10;

/** Records whose chosen fields are empty — any of them, or all of them. */
export function EmptyFieldsFinder({ object }: { object: string }) {
  const options = useEmptyOptions(object);
  const [chosen, setChosen] = useState<string[]>([]);
  const [match, setMatch] = useState<'any' | 'all'>('any');
  const [fieldQuery, setFieldQuery] = useState('');
  const [rowQuery, setRowQuery] = useState('');
  const [result, setResult] = useState<EmptyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setChosen([]);
    setResult(null);
    setError(null);
  }, [object]);

  const fields = options.data ?? [];
  const fieldList = fields.filter((f) => !fieldQuery || `${f.label} ${f.name}`.toLowerCase().includes(fieldQuery.toLowerCase()));
  const label = (name: string) => fields.find((f) => f.name === name)?.label ?? name;

  const run = async (cursor?: string) => {
    setBusy(true);
    setError(null);
    try {
      const page = await dataApi.findEmpty({ object, fields: chosen, match, cursor });
      setResult((prev) => (cursor && prev ? { ...page, objectTotal: prev.objectTotal, records: [...prev.records, ...page.records] } : page));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const term = rowQuery.trim().toLowerCase();
  const rows = (result?.records ?? []).filter(
    (r) => !term || [...Object.values(r.values), ...Object.values(r.refNames)].some((v) => v != null && String(v).toLowerCase().includes(term)),
  );
  const cols = result ? result.columns.filter((c) => c.type !== 'id').slice(0, Math.max(8, result.fields.length + 2)) : [];
  const emptyCount = result?.totalSize ?? 0;
  const total = result?.objectTotal ?? null;
  const what = objectLabel(object).toLowerCase();

  if (options.isLoading) return <LoadingState rows={3} label="Reading this object’s fields…" />;
  if (options.error) return <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">{errorMessage(options.error)}</p>;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-line p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <p className="min-w-0 flex-1 text-sm">
            Show {what} where{' '}
            <select className="input inline h-8 w-auto py-0 text-sm" value={match} onChange={(e) => setMatch(e.target.value as 'any' | 'all')}>
              <option value="any">any</option>
              <option value="all">all</option>
            </select>{' '}
            of the fields you pick {match === 'all' ? 'are' : 'is'} empty. <span className="text-ink-muted">({chosen.length}/{MAX_FIELDS} chosen)</span>
          </p>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
            <input className="input h-8 w-56 pl-8 text-xs" placeholder="Filter fields…" value={fieldQuery} onChange={(e) => setFieldQuery(e.target.value)} />
          </div>
        </div>
        {chosen.length > 0 && (
          <p className="mb-2 text-xs text-ink-muted">
            Checking: <span className="font-medium text-ink">{chosen.map(label).join(match === 'all' ? ' and ' : ' or ')}</span>
            <button type="button" className="ml-2 text-brand hover:underline" onClick={() => setChosen([])}>Clear</button>
          </p>
        )}
        <div className="scrollbar-thin grid max-h-64 gap-1.5 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
          {fieldList.map((f) => {
            const on = chosen.includes(f.name);
            return (
              <label
                key={f.name}
                className={cx(
                  'flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm transition',
                  on ? 'border-brand bg-brand-soft/60' : 'border-line hover:border-brand/30',
                  !on && chosen.length >= MAX_FIELDS && 'cursor-not-allowed opacity-50',
                )}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 accent-[rgb(var(--brand))]"
                  checked={on}
                  disabled={!on && chosen.length >= MAX_FIELDS}
                  onChange={(e) => setChosen(e.target.checked ? [...chosen, f.name] : chosen.filter((x) => x !== f.name))}
                />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{f.label}</span>
                  <span className="block truncate text-[11px] text-ink-subtle">{f.name} · {f.type}</span>
                </span>
              </label>
            );
          })}
          {fieldList.length === 0 && <p className="text-xs text-ink-subtle">No fields match “{fieldQuery}”.</p>}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" icon={<Search className="h-4 w-4" />} disabled={!chosen.length || busy} onClick={() => run()}>
          {busy && !result ? 'Looking…' : `Find ${what} with empty fields`}
        </Button>
      </div>
      {error != null && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(error)}</p>}

      {result && (
        <div className="space-y-3">
          {/* the result in order: checked → empty → filled in */}
          <ol className="grid gap-2 sm:grid-cols-3">
            {[
              { n: 1, label: `${objectLabel(object)} checked`, value: total ?? 0, hint: 'All records of this object', tone: 'text-ink', box: 'border-line bg-muted/40' },
              {
                n: 2,
                label: `With ${match === 'all' ? 'all' : 'any'} chosen field${result.fields.length === 1 ? '' : 's'} empty`,
                value: emptyCount,
                hint: total ? `${Math.round((100 * emptyCount) / total)}% of all ${what}` : result.fieldLabels.join(', '),
                tone: 'text-bad',
                box: 'border-bad/30 bg-bad-soft/40',
              },
              { n: 3, label: 'Filled in', value: Math.max((total ?? 0) - emptyCount, 0), hint: total ? `${Math.round((100 * Math.max(total - emptyCount, 0)) / total)}% complete` : '', tone: 'text-good', box: 'border-good/30 bg-good-soft/40' },
            ].map((st, i, all) => (
              <li key={st.n} className="relative flex">
                <div className={cx('flex w-full flex-col rounded-xl border px-4 py-3', st.box)}>
                  <span className="flex items-center gap-2 text-xs font-medium text-ink-muted">
                    <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface text-[11px] font-bold text-ink ring-1 ring-line">{st.n}</span>
                    {st.label}
                  </span>
                  <span className={cx('mt-1.5 text-2xl font-semibold tabular-nums tracking-tight', st.tone)}>
                    <AnimatedNumber value={st.value} />
                  </span>
                  {st.hint && <span className="mt-0.5 text-[11px] leading-snug text-ink-muted">{st.hint}</span>}
                </div>
                {i < all.length - 1 && <ChevronRight className="absolute -right-2.5 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 rounded-full bg-surface text-ink-subtle ring-1 ring-line sm:block" aria-hidden="true" />}
              </li>
            ))}
          </ol>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
              <input className="input h-9 pl-8 text-sm" placeholder="Filter by any value (name, owner…)" value={rowQuery} onChange={(e) => setRowQuery(e.target.value)} />
            </div>
            <a
              href={dataApi.emptyCsvUrl(object, result.fields, match)}
              download
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-xs font-medium hover:bg-muted"
              title="Download these records (up to 10,000)"
            >
              <Download className="h-3.5 w-3.5" /> CSV
            </a>
          </div>

          {rows.length === 0 ? (
            <p className="rounded-lg bg-muted/50 px-4 py-6 text-center text-sm text-ink-muted">
              {emptyCount ? `No loaded records match “${rowQuery}”.` : `Every ${objectLabel(object).toLowerCase().replace(/s$/, '')} has ${match === 'all' ? 'at least one of' : 'all of'} these fields filled in.`}
            </p>
          ) : (
            <div className="scrollbar-thin max-h-[32rem] overflow-auto rounded-xl border border-line">
              <table className="w-full min-w-[720px] text-left text-xs">
                <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgb(var(--line))]">
                  <tr>
                    {cols.map((c) => (
                      <th
                        key={c.name}
                        className={cx('whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-wide', result.fields.includes(c.name) ? 'bg-bad-soft/40 text-bad' : 'text-ink-subtle')}
                      >
                        {c.type === 'reference' ? c.label.replace(/ ID$/, '') : c.label}
                      </th>
                    ))}
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.map((r, ri) => {
                    const href = r.id ? `${result.recordUrlPrefix}${r.id}` : undefined;
                    return (
                      <tr key={r.id ?? ri} className="group hover:bg-muted/60">
                        {cols.map((c, ci) => {
                          const raw = r.values[c.name];
                          const blank = raw === null || raw === undefined || raw === '';
                          const v = formatValue(c as unknown as DataField, raw, r.refNames[c.name]);
                          return (
                            <td key={c.name} className="max-w-[16rem] truncate px-3 py-2" title={v}>
                              {result.fields.includes(c.name) && blank ? (
                                <span className="rounded bg-bad-soft px-1.5 py-0.5 text-[11px] font-semibold text-bad">Empty</span>
                              ) : ci === 0 && href ? (
                                <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-brand hover:underline">{v === '—' ? r.id : v}</a>
                              ) : (
                                <span className={v === '—' ? 'text-ink-subtle' : ''}>{v}</span>
                              )}
                            </td>
                          );
                        })}
                        <td className="px-2">
                          {href && (
                            <a href={href} target="_blank" rel="noopener noreferrer" aria-label="Open in Salesforce" className="text-ink-subtle opacity-0 transition hover:text-brand group-hover:opacity-100">
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {result.nextCursor && (
            <div className="text-center">
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(result.nextCursor!)}>
                {busy ? 'Loading…' : `Show more (${fmtNumber(result.records.length)} of ${fmtNumber(emptyCount)})`}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
