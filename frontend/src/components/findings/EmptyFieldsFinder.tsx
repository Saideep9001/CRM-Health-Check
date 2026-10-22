import { Download, ExternalLink, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { errorMessage } from '@/api/client';
import { dataApi } from '@/api/endpoints';
import { objectLabel } from '@/components/category/DiagnosticAreaCard';
import { formatValue } from '@/components/data/format';
import { cx, fmtNumber } from '@/lib/format';
import type { DataField, EmptyResult } from '@/types';
import { Button } from '../ui/Button';
import { LoadingState } from '../ui/States';

/** Fields named in a check's "Fields checked" text (by label or API name), for this object only. */
export function fieldsNamed(text: string, object: string, fields: { name: string; label: string }[], max: number): string[] {
  const own = text.split(';').find((part) => part.toLowerCase().trim().startsWith(`${objectLabel(object).toLowerCase()}:`));
  const hay = ` ${(own ?? text).toLowerCase().replace(/[^a-z0-9_]+/g, ' ')} `;
  const has = (s: string) => hay.includes(` ${s.toLowerCase().replace(/[^a-z0-9_]+/g, ' ').trim()} `);
  return fields.filter((f) => has(f.label) || has(f.name)).map((f) => f.name).slice(0, max);
}

/** Records where the given field(s) are empty, 200 at a time, with a value filter and CSV. */
export function EmptyRecords({ object, fields }: { object: string; fields: string[] }) {
  const [rowQuery, setRowQuery] = useState('');
  const [result, setResult] = useState<EmptyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const run = async (cursor?: string) => {
    setBusy(true);
    setError(null);
    try {
      const page = await dataApi.findEmpty({ object, fields, match: 'any', cursor });
      setResult((prev) => (cursor && prev ? { ...page, objectTotal: prev.objectTotal, records: [...prev.records, ...page.records] } : page));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const key = `${object}|${fields.join(',')}`;
  useEffect(() => {
    setResult(null);
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (error != null) return <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(error)}</p>;
  if (!result) return <LoadingState rows={3} label="Loading the records…" />;

  const term = rowQuery.trim().toLowerCase();
  const rows = result.records.filter(
    (r) => !term || [...Object.values(r.values), ...Object.values(r.refNames)].some((v) => v != null && String(v).toLowerCase().includes(term)),
  );
  const cols = result.columns.filter((c) => c.type !== 'id').slice(0, Math.max(8, result.fields.length + 2));
  const emptyCount = result.totalSize ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-subtle" />
          <input className="input h-9 pl-8 text-sm" placeholder="Filter by any value (name, owner…)" value={rowQuery} onChange={(e) => setRowQuery(e.target.value)} />
        </div>
        <a
          href={dataApi.emptyCsvUrl(object, result.fields, 'any')}
          download
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-xs font-medium hover:bg-muted"
          title="Download these records (up to 10,000)"
        >
          <Download className="h-3.5 w-3.5" /> CSV
        </a>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-lg bg-muted/50 px-4 py-6 text-center text-sm text-ink-muted">
          {emptyCount ? `No loaded records match “${rowQuery}”.` : `Every ${objectLabel(object).toLowerCase().replace(/s$/, '')} has this filled in.`}
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
  );
}
