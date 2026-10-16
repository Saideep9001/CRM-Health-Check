import { CalendarCheck2, Hourglass, Layers, ListChecks } from 'lucide-react';
import { RunCheckPanel } from '@/components/assessment/RunCheckPanel';
import { CategoryCard } from '@/components/dashboard/CategoryCard';
import { InfoTip } from '@/components/ui/HelpTip';
import { PageHeader, StaggerGrid, StaggerItem } from '@/components/ui/Page';
import { CATEGORIES, DIAGNOSTIC_AREAS, MVP_AREA_IDS, getAreaRelease } from '@/config/categories';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { fmtDate } from '@/lib/format';

export default function AssessmentOverviewPage() {
  const { latest, results, findings } = useLatestAssessment();
  const mvp = DIAGNOSTIC_AREAS.filter((a) => getAreaRelease(a) === 'mvp').length;
  const assessed = results ? results.areas.filter((a) => a.status === 'assessed').length : 0;

  const stats = [
    { icon: Layers, label: 'Areas we check', value: DIAGNOSTIC_AREAS.length, text: 'Grouped into six topics.' },
    { icon: ListChecks, label: 'Ready to check', value: mvp, text: 'Areas you can check today.' },
    { icon: Hourglass, label: 'Coming Soon', value: DIAGNOSTIC_AREAS.length - mvp, text: 'Coming in a later release.' },
    {
      icon: CalendarCheck2,
      label: 'Checked last time',
      value: latest ? assessed : '—',
      text: latest ? `${latest.name} · ${fmtDate(latest.completedAt ?? latest.createdAt)}` : 'You haven’t run a health check yet.',
    },
  ];

  return (
    <div>
      <PageHeader
        title="What We Check"
        description="6 topics, 21 areas. Click a topic to learn more."
      />

      <RunCheckPanel areaIds={MVP_AREA_IDS} label="everything that’s ready" checked={!!latest} lastChecked={latest?.completedAt} objectPicker />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="card flex items-start gap-3 p-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-ink">
              <s.icon className="h-[18px] w-[18px]" />
            </span>
            <div className="min-w-0">
              <p className="flex items-center gap-1 text-xs text-ink-subtle">
                {s.label}
                <InfoTip>{s.text}</InfoTip>
              </p>
              <p className="text-2xl font-semibold leading-tight tabular-nums">{s.value}</p>
            </div>
          </div>
        ))}
      </div>

      <StaggerGrid className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {CATEGORIES.map((c) => (
          <StaggerItem key={c.id}>
            <CategoryCard category={c} results={results} findings={findings} />
          </StaggerItem>
        ))}
      </StaggerGrid>
    </div>
  );
}
