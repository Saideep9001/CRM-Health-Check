import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { indicatorApi } from '@/api/endpoints';
import { cx, fmtNumber } from '@/lib/format';
import { FilterChips } from './EacHealth';

/** Email template availability: every email template with its Description (what it's for), Type, Status and its share of
 *  all template use, read live from Salesforce. The Status chips pick all, active or inactive templates. */
export function EmailTemplates({ assessmentId }: { assessmentId: string }) {
  const [status, setStatus] = useState<string | undefined>();
  const data = useQuery({
    queryKey: ['email-templates', assessmentId, status ?? 'all'],
    queryFn: ({ signal }) => indicatorApi.emailTemplates(assessmentId, status ?? 'all', signal),
    staleTime: 60_000,
    placeholderData: (prev) => prev, // keep the table while another status loads
  });
  if (data.isLoading) return <p className="text-sm text-ink-subtle">Reading the email templates from Salesforce…</p>;
  if (data.error) return <p className="rounded-lg bg-bad-soft/50 px-4 py-3 text-sm text-bad">Couldn’t read the email templates: {(data.error as Error).message}</p>;
  const d = data.data!;

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-line px-3 py-2">
        <FilterChips
          title="Status"
          value={status}
          onChange={setStatus}
          options={[
            { key: 'active', label: 'Active', tone: 'good', count: d.counts.active },
            { key: 'inactive', label: 'Inactive', tone: 'bad', count: d.counts.inactive },
          ]}
        />
      </div>

      <div className="overflow-hidden rounded-xl border border-line">
        <div className="flex items-center justify-between gap-2 bg-muted/40 px-3 py-2 text-xs">
          <span className="font-semibold text-ink">Email templates</span>
          <span className="text-ink-muted">
            {fmtNumber(d.templates.length)} {d.status === 'all' ? '' : d.status} template{d.templates.length === 1 ? '' : 's'}, most used first
          </span>
        </div>
        <div className="max-h-[32rem] overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-ink-muted">
              <tr className="border-b border-line">
                <th className="px-3 py-2 font-medium">Email Template Name</th>
                <th className="px-3 py-2 font-medium">Description (what it’s for)</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 text-right font-medium">Times used</th>
                <th className="px-3 py-2 text-right font-medium">Usage %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {!d.templates.length && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-xs text-ink-subtle">No templates with this status.</td>
                </tr>
              )}
              {d.templates.map((t) => (
                <tr key={t.id} className="align-top">
                  <td className="max-w-[16rem] px-3 py-2 font-medium">
                    <span className="block truncate" title={t.folder ? `${t.name} (folder: ${t.folder})` : t.name}>{t.name}</span>
                  </td>
                  <td className="min-w-[16rem] max-w-[28rem] whitespace-pre-line px-3 py-2 text-ink-muted">
                    {t.description || <span className="text-ink-subtle">No description in Salesforce</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-ink-muted">{t.type}</td>
                  <td className="px-3 py-2">
                    <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium', t.active ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
                      {t.active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{t.timesUsed == null ? '—' : fmtNumber(t.timesUsed)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{t.usagePct == null ? '—' : `${t.usagePct}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-[11px] text-ink-subtle">
        Read live from Salesforce. Description is the template’s own Description field. Usage % = its Times Used out of all templates’ Times
        Used{d.totalUsed != null ? ` (${fmtNumber(d.totalUsed)} in all)` : ''}.{d.truncated ? ' Showing the first 2,000 templates.' : ''}
      </p>
    </div>
  );
}
