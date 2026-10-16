import { FilterX, Play, SearchX } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useAssessments } from '@/api/queries';
import { AssessmentTable } from '@/components/assessments/AssessmentTable';
import { ASSESSMENT_STATUS_LABEL } from '@/components/ui/Badges';
import { Button, LinkButton } from '@/components/ui/Button';
import { SearchInput, Select } from '@/components/ui/Form';
import { PageHeader } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { CATEGORIES } from '@/config/categories';
import type { AssessmentStatus, CategoryId } from '@/types';

export default function HistoryPage() {
  const { data, isLoading, error, refetch } = useAssessments();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<'all' | AssessmentStatus>('all');
  const [category, setCategory] = useState<'all' | CategoryId>('all');
  const [org, setOrg] = useState('all');

  const orgs = useMemo(() => [...new Set((data ?? []).map((a) => a.organizationName))], [data]);
  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (data ?? []).filter(
      (a) =>
        (!term || a.name.toLowerCase().includes(term) || a.id.toLowerCase().includes(term) || a.organizationName.toLowerCase().includes(term)) &&
        (status === 'all' || a.status === status) &&
        (category === 'all' || a.scope.categoryIds.includes(category)) &&
        (org === 'all' || a.organizationName === org),
    );
  }, [data, q, status, category, org]);

  const anyFilter = q || status !== 'all' || category !== 'all' || org !== 'all';
  const clear = () => {
    setQ('');
    setStatus('all');
    setCategory('all');
    setOrg('all');
  };

  return (
    <div>
      <PageHeader
        title="Check History"
        description="All your past health checks."
        actions={
          <LinkButton to="/assessment" variant="primary" icon={<Play className="h-4 w-4" />}>
            Run a health check
          </LinkButton>
        }
      />
      <div className="card">
        <div className="flex flex-col gap-3 border-b border-line p-4 lg:flex-row lg:items-center">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or Salesforce…" className="lg:w-80" />
          <div className="grid flex-1 gap-2 sm:grid-cols-3">
            <Select
              label="Status"
              value={status}
              onChange={setStatus}
              options={[
                { value: 'all', label: 'All statuses' },
                ...(Object.keys(ASSESSMENT_STATUS_LABEL) as AssessmentStatus[]).map((s) => ({ value: s, label: ASSESSMENT_STATUS_LABEL[s] })),
              ]}
            />
            <Select<'all' | CategoryId>
              label="Topic"
              value={category}
              onChange={setCategory}
              options={[{ value: 'all', label: 'All topics' }, ...CATEGORIES.map((c) => ({ value: c.id, label: c.name }))]}
            />
            <Select label="Organization" value={org} onChange={setOrg} options={[{ value: 'all', label: 'All Salesforce orgs' }, ...orgs.map((o) => ({ value: o, label: o }))]} />
          </div>
          {anyFilter && (
            <Button size="sm" variant="ghost" icon={<FilterX className="h-4 w-4" />} onClick={clear}>
              Clear
            </Button>
          )}
        </div>
        {data && data.length > 0 && (
          <p className="px-4 py-2.5 text-xs text-ink-subtle">
            Showing <span className="font-semibold text-ink">{rows.length}</span> of {data.length} health checks
          </p>
        )}
        {isLoading ? (
          <LoadingState rows={8} />
        ) : error ? (
          <ErrorState error={error} onRetry={() => refetch()} />
        ) : !data?.length ? (
          <EmptyState
            title="No health checks yet"
            description="Your checks will show here."
            action={
              <LinkButton to="/assessment" size="sm" variant="primary">
                Run a health check
              </LinkButton>
            }
          />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<SearchX className="h-6 w-6" />}
            title="Nothing matches your filters"
            description="Try adjusting your search or filters."
            action={
              <Button size="sm" onClick={clear}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <AssessmentTable rows={rows} variant="history" />
        )}
      </div>
    </div>
  );
}
