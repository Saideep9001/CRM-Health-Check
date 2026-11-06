import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { indicatorApi, type EmailTemplatesData } from '@/api/endpoints';
import { LocalTable, type LocalColumn } from '@/components/data/LocalTable';
import { cx, fmtNumber } from '@/lib/format';
import { FilterChips } from './EacHealth';

type Template = EmailTemplatesData['templates'][number];

const COLUMNS: LocalColumn<Template>[] = [
  {
    key: 'name',
    label: 'Email Template Name',
    value: (t) => t.name,
    className: 'max-w-[18rem] font-medium',
    render: (t) => <span className="block truncate" title={t.folder ? `${t.name} (folder: ${t.folder})` : t.name}>{t.name}</span>,
  },
  {
    key: 'description',
    label: 'Description (what it’s for)',
    name: 'Description',
    value: (t) => t.description,
    className: 'min-w-[16rem] max-w-[28rem] whitespace-pre-line text-ink-muted',
    render: (t) => t.description || <span className="text-ink-subtle">No description in Salesforce</span>,
  },
  { key: 'type', label: 'Type', value: (t) => t.type, className: 'whitespace-nowrap text-ink-muted' },
  {
    key: 'status',
    label: 'Status',
    value: (t) => (t.active ? 'Active' : 'Inactive'),
    render: (t) => (
      <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium', t.active ? 'bg-good-soft text-good' : 'bg-bad-soft text-bad')}>
        {t.active ? 'Active' : 'Inactive'}
      </span>
    ),
  },
  { key: 'timesUsed', label: 'Times used', align: 'right', value: (t) => t.timesUsed, render: (t) => (t.timesUsed == null ? '—' : fmtNumber(t.timesUsed)) },
  { key: 'usagePct', label: 'Usage %', align: 'right', value: (t) => t.usagePct, render: (t) => (t.usagePct == null ? '—' : `${t.usagePct}%`) },
];

/** Email template availability: every email template with its Description (what it's for), Type, Status and its share of
 *  all template use, read live from Salesforce. The Status chips pick all, active or inactive templates; every column has an
 *  Excel-style filter, and the table can be expanded. */
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
      <LocalTable
        title={`Email templates${d.status === 'all' ? '' : ` (${d.status})`}, most used first`}
        rows={d.templates}
        columns={COLUMNS}
        rowKey={(t) => t.id}
        empty="No templates with this status."
      />
      <p className="text-[11px] text-ink-subtle">
        Read live from Salesforce. Description is the template’s own Description field. Usage % = its Times Used out of all templates’ Times
        Used{d.totalUsed != null ? ` (${fmtNumber(d.totalUsed)} in all)` : ''}.{d.truncated ? ' Showing the first 2,000 templates.' : ''}
      </p>
    </div>
  );
}
