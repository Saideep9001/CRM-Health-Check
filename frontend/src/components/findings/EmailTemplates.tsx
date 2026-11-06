import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { indicatorApi } from '@/api/endpoints';
import { cx, fmtNumber } from '@/lib/format';
import { FilterChips } from './EacHealth';

/** A share list: one bar per object with its % and count. */
function Shares({ title, tip, rows, empty }: { title: string; tip: string; rows: { area: string; timesUsed: number; pct: number }[]; empty: string }) {
  const max = Math.max(1, ...rows.map((a) => a.pct));
  return (
    <div className="rounded-xl border border-line p-3">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle" title={tip}>{title}</p>
      {!rows.length ? (
        <p className="text-xs text-ink-subtle">{empty}</p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((a) => (
            <li key={a.area} className="grid grid-cols-[9rem_1fr_6rem] items-center gap-2 text-xs">
              <span className="truncate" title={a.area}>{a.area}</span>
              <span className="h-2 rounded-full bg-muted">
                <span className="block h-2 rounded-full bg-brand" style={{ width: `${(a.pct / max) * 100}%` }} />
              </span>
              <span className="text-right tabular-nums text-ink-muted">
                {a.pct}% <span className="text-ink-subtle">({fmtNumber(a.timesUsed)})</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Email template availability: every email template with its Type, Status, the area (object) it's used for and its share
 *  of all template use, read live from Salesforce. The Status chips pick all, active or inactive templates. */
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

      <div className="grid gap-3 sm:grid-cols-2">
        <Shares
          title="Emails sent with templates, by object"
          tip="From the org’s sent emails: the object of the record each was sent from, or of the person it went to."
          rows={d.sentObjects}
          empty={d.sentAvailable ? 'No sent emails with a template found.' : 'Sent emails can’t be read with this user.'}
        />
        <Shares title="Template use by area (Times Used)" tip="Each template’s Times Used, by the object it’s set up for." rows={d.areas} empty="No template use recorded." />
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
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Used in (area)</th>
                <th className="px-3 py-2 font-medium">Most used on</th>
                <th className="px-3 py-2 text-right font-medium">Times used</th>
                <th className="px-3 py-2 text-right font-medium">Usage %</th>
                <th className="px-3 py-2 font-medium">Last used</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {!d.templates.length && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-xs text-ink-subtle">No templates with this status.</td>
                </tr>
              )}
              {d.templates.map((t) => (
                <tr key={t.id}>
                  <td className="max-w-[18rem] px-3 py-2 font-medium">
                    <span className="block truncate" title={t.folder ? `${t.name} (folder: ${t.folder})` : t.name}>{t.name}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-ink-muted">{t.type}</td>
                  <td className="px-3 py-2">
                    <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium', t.active ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
                      {t.active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-ink-muted">{t.area}</td>
                  <td className="px-3 py-2 text-ink-muted" title={t.sentFrom.map((s) => `${s.object}: ${s.count}`).join(' · ')}>
                    {t.mostUsedOn ? (
                      <>
                        <span className="font-medium text-ink">{t.mostUsedOn}</span>{' '}
                        <span className="text-ink-subtle">
                          ({fmtNumber(t.sentFrom[0].count)} of {fmtNumber(t.sent)} sent)
                        </span>
                      </>
                    ) : (
                      <span className="text-ink-subtle">{d.sentAvailable ? 'No sent emails' : '—'}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{t.timesUsed == null ? '—' : fmtNumber(t.timesUsed)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{t.usagePct == null ? '—' : `${t.usagePct}%`}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-ink-muted">{t.lastUsed ?? 'Never'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-[11px] text-ink-subtle">
        Read live from Salesforce. Used in = the object a template is for (Lightning templates); Usage % = its Times Used out of all
        templates’ Times Used{d.totalUsed != null ? ` (${fmtNumber(d.totalUsed)} in all)` : ''}. Most used on = the object it was sent from most, from
        the org’s sent emails (emails sent before Enhanced Email or outside Salesforce aren’t kept, so they can’t be counted).
        {d.sentCapped ? ' Based on the latest 20,000 sent emails.' : ''}{d.truncated ? ' Showing the first 2,000 templates.' : ''}
      </p>
    </div>
  );
}
