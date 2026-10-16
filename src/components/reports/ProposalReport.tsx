import { FileSpreadsheet, RotateCcw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useProposal, useSettings } from '@/api/queries';
import { Button } from '@/components/ui/Button';
import { SeverityBadge } from '@/components/ui/Badges';
import { ErrorState, LoadingState } from '@/components/ui/States';
import { getArea, getCategory } from '@/config/categories';
import { cx, fmtNumber } from '@/lib/format';
import type { Assessment, ProposalLine } from '@/types';
import { BrandedFooter, BrandedHeader, useBranding } from './Branding';

const HOURS_PER_WEEK = 30;

const money = (v: number, currency: string) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(v);

function csv(lines: ProposalLine[], hours: Record<string, number>, rate: number) {
  const esc = (v: string | number) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const rows = lines.map((l) => [l.phase, l.name, getCategory(l.categoryId)?.name ?? l.categoryId, l.severity, l.affectedRecords, hours[l.findingId] ?? l.hours, (hours[l.findingId] ?? l.hours) * rate, l.action]);
  return [['Phase', 'Work item', 'Topic', 'Urgency', 'Records affected', 'Hours', 'Cost', 'What we will do'], ...rows].map((r) => r.map(esc).join(',')).join('\r\n');
}

/**
 * A statement of work drafted from the health check: three phases, effort and cost per problem, value at risk.
 * Hours, rate and what's included can be edited before printing — the estimates are a starting point.
 */
export function ProposalReport({ assessment }: { assessment: Assessment }) {
  const settings = useSettings();
  const branding = useBranding();
  const [rate, setRate] = useState<number | null>(null);
  const currency = settings.data?.currency ?? 'USD';
  const effectiveRate = rate ?? settings.data?.hourlyRate ?? 150;
  const q = useProposal(settings.isLoading ? null : assessment.id, effectiveRate, currency);
  const [hours, setHours] = useState<Record<string, number>>({});
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  useEffect(() => {
    setHours({});
    setExcluded(new Set());
  }, [assessment.id]);

  const p = q.data;
  const lines = useMemo(() => (p?.lines ?? []).filter((l) => !excluded.has(l.findingId)), [p, excluded]);
  const h = (l: ProposalLine) => hours[l.findingId] ?? l.hours;
  let weekCursor = 0;
  const phases = (p?.phases ?? []).map((ph) => {
    const ls = lines.filter((l) => l.phase === ph.id);
    const hrs = ls.reduce((a, l) => a + h(l), 0);
    const weeks = hrs ? Math.max(1, Math.ceil(hrs / HOURS_PER_WEEK)) : 0;
    const range = weeks ? (weeks === 1 ? `Week ${weekCursor + 1}` : `Weeks ${weekCursor + 1}–${weekCursor + weeks}`) : null;
    weekCursor += weeks;
    return { ...ph, lines: ls, hours: hrs, cost: hrs * effectiveRate, range };
  });
  const totalHours = phases.reduce((a, ph) => a + ph.hours, 0);
  const edited = Object.keys(hours).length > 0 || excluded.size > 0;

  if (q.isLoading || settings.isLoading) return <div className="card"><LoadingState rows={8} label="Drafting the proposal…" /></div>;
  if (q.error || !p) return <div className="card"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>;

  const download = () => {
    const url = URL.createObjectURL(new Blob(['﻿' + csv(lines, hours, effectiveRate)], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `proposal-${p.organizationName.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div>
      <div className="no-print card mb-4 flex flex-wrap items-center gap-3 p-4 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-ink-muted">Hourly rate ({currency})</span>
          <input type="number" min={0} max={5000} value={effectiveRate} onChange={(e) => setRate(Math.max(0, Number(e.target.value) || 0))} className="input w-28" />
        </label>
        <span className="text-xs text-ink-subtle">Estimates are a starting point — edit hours, untick work you won’t propose, then print.</span>
        <div className="ml-auto flex gap-2">
          {edited && <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => { setHours({}); setExcluded(new Set()); }}>Reset edits</Button>}
          <Button size="sm" icon={<FileSpreadsheet className="h-3.5 w-3.5" />} onClick={download}>Download as spreadsheet</Button>
        </div>
      </div>

      <article className="relative mx-auto max-w-4xl overflow-hidden rounded-xl border border-line bg-surface shadow-card">
        <BrandedHeader branding={branding} title="Proposal & statement of work" subtitle={`${p.organizationName} · based on ${assessment.name}`} />
        <div className="px-8 py-6">
          <section className="mb-6">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-ink-subtle">
              Summary
            </h3>
            <p className="text-sm leading-relaxed">{p.summary}</p>
          </section>

          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              ['Health score today', p.overallScore ?? '—'],
              ['Work items', lines.length],
              ['Effort', `${fmtNumber(Math.round(totalHours))} hours`],
              ['Investment', money(totalHours * effectiveRate, currency)],
            ].map(([k, v]) => (
              <div key={k as string} className="rounded-lg border border-line px-3 py-2">
                <p className="text-[11px] uppercase tracking-wide text-ink-subtle">{k}</p>
                <p className="mt-0.5 text-lg font-semibold tabular-nums">{v}</p>
              </div>
            ))}
          </div>
          {p.valueAtRisk ? (
            <p className="-mt-3 mb-6 text-xs text-ink-muted">
              The largest single problem puts {money(p.valueAtRisk, currency)} of pipeline or revenue at risk (problems can overlap, so values aren’t added up).
            </p>
          ) : null}

          {phases.map((ph) => (
            <section key={ph.id} className="mb-6 break-inside-avoid">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-1">
                <h3 className="text-base font-semibold">{ph.name}</h3>
                <p className="text-sm tabular-nums text-ink-muted">{fmtNumber(Math.round(ph.hours))} h · {money(ph.cost, currency)}</p>
              </div>
              <p className="mb-2 text-xs text-ink-subtle">{ph.range ? `${ph.range} (one consultant): ` : ''}{ph.description}</p>
              {ph.lines.length === 0 ? (
                <p className="text-sm text-ink-subtle">Nothing in this phase.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-ink-subtle">
                      <th className="py-1.5">Work item</th>
                      <th className="px-2">Urgency</th>
                      <th className="px-2 text-right">Records</th>
                      <th className="w-24 px-2 text-right">Hours</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ph.lines.map((l) => {
                      const area = getArea(l.areaId);
                      return (
                        <tr key={l.findingId} className="border-t border-line align-top">
                          <td className="py-2 pr-2">
                            <span className="font-medium">{l.name}</span>
                            <span className="block text-xs text-ink-subtle">{getCategory(l.categoryId)?.shortName}{area ? ` · Area ${area.number}` : ''} — {l.action}</span>
                          </td>
                          <td className="px-2 py-2"><SeverityBadge severity={l.severity} /></td>
                          <td className="px-2 py-2 text-right tabular-nums">{l.affectedRecords ? fmtNumber(l.affectedRecords) : '—'}</td>
                          <td className="px-2 py-2 text-right">
                            <input
                              type="number"
                              min={0}
                              step={0.5}
                              value={h(l)}
                              onChange={(e) => setHours((x) => ({ ...x, [l.findingId]: Math.max(0, Number(e.target.value) || 0) }))}
                              className={cx('no-print input h-7 w-20 text-right tabular-nums', hours[l.findingId] !== undefined && 'border-brand')}
                              aria-label={`Hours for ${l.name}`}
                            />
                            <span className="print-only tabular-nums">{h(l)}</span>
                            <button className="no-print mt-1 block w-full text-right text-[11px] text-ink-subtle hover:text-bad" onClick={() => setExcluded((s) => new Set(s).add(l.findingId))}>
                              Leave out
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>
          ))}
          {excluded.size > 0 && (
            <p className="no-print text-xs text-ink-subtle">
              {excluded.size} item{excluded.size === 1 ? '' : 's'} left out.{' '}
              <button className="font-medium text-brand hover:underline" onClick={() => setExcluded(new Set())}>Put them back</button>
            </p>
          )}

          <section className="mt-6 break-inside-avoid rounded-lg bg-muted/50 p-4 text-sm">
            <h3 className="mb-1 font-semibold">How we’ll measure success</h3>
            <p className="text-ink-muted">
              We re-run the health check at the end of each phase. Problems that are fixed move to “Fixed since last check”, and the health score
              should rise from {p.overallScore ?? '—'} towards 80+ (healthy). Timeline: about {weekCursor} weeks for one consultant at {HOURS_PER_WEEK} hours a week (shorter with a bigger team).
            </p>
          </section>
        </div>
        <BrandedFooter branding={branding} />
      </article>
    </div>
  );
}
