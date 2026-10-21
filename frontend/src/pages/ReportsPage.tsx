import { BarChart3, Briefcase, FileDown, FileSpreadsheet, FileText, History, LayoutDashboard, PieChart, Play, Printer, ScrollText } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useAssessmentResults, useAssessments, useFindings } from '@/api/queries';
import { BenchmarkCard } from '@/components/reports/BenchmarkCard';
import { ProposalReport } from '@/components/reports/ProposalReport';
import { ReportDashboard } from '@/components/reports/ReportDashboard';
import { REPORT_TITLES, ReportPreview } from '@/components/reports/ReportPreview';
import { Button, LinkButton } from '@/components/ui/Button';
import { Select } from '@/components/ui/Form';
import { InfoTip } from '@/components/ui/HelpTip';
import { PageHeader } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { Segmented, Tabs } from '@/components/ui/Tabs';
import { CATEGORIES, getArea, getCategory } from '@/config/categories';
import { useToast } from '@/context/ToastContext';
import { fmtDate } from '@/lib/format';
import { countBySeverity, getCategoryScore } from '@/lib/health';
import { KpiCards } from '@/components/reports/KpiCards';
import type { CategoryId, Finding, ReportType } from '@/types';

type Range = '30d' | '90d' | '12m' | 'all';
const RANGE_DAYS: Record<Range, number | null> = { '30d': 30, '90d': 90, '12m': 365, all: null };
const RANGE_LABEL: Record<Range, string> = { '30d': 'Last 30 days', '90d': 'Last 90 days', '12m': 'Last 12 months', all: 'All time' };

/** "dashboard" is a charts view on screen; the others are printable/downloadable reports. */
type View = 'dashboard' | ReportType;

const TABS: { id: View; label: string; icon: JSX.Element }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard className="h-4 w-4" /> },
  { id: 'executive', label: 'Leadership summary', icon: <ScrollText className="h-4 w-4" /> },
  { id: 'category', label: 'Score by topic', icon: <BarChart3 className="h-4 w-4" /> },
  { id: 'findings', label: 'All problems', icon: <FileText className="h-4 w-4" /> },
  { id: 'severity', label: 'By urgency', icon: <PieChart className="h-4 w-4" /> },
  { id: 'history', label: 'History', icon: <History className="h-4 w-4" /> },
  { id: 'proposal', label: 'Proposal (SOW)', icon: <Briefcase className="h-4 w-4" /> },
];

const csvEscape = (v: string | number) => {
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

function findingsCsv(findings: Finding[]) {
  const cols = ['Problem ID', 'Problem', 'Topic', 'Area', 'Urgency', 'Records affected', 'Why it matters', 'How to fix it', 'Progress', 'When to fix', 'Found on'];
  const rows = findings.map((f) => {
    const area = getArea(f.areaId);
    return [f.id, f.name, getCategory(f.categoryId)?.name ?? f.categoryId, area ? `Area ${area.number}: ${area.name}` : f.areaId, f.severity, f.affectedRecords, f.businessImpact, f.recommendedAction, f.status, f.priority, f.detectedAt];
  });
  return [cols, ...rows].map((r) => r.map(csvEscape).join(',')).join('\r\n');
}

export default function ReportsPage() {
  const { notify } = useToast();
  const list = useAssessments();
  const completed = useMemo(() => (list.data ?? []).filter((a) => a.status === 'completed'), [list.data]);
  const [assessmentId, setAssessmentId] = useState<string | null>(null);
  const activeId = assessmentId ?? completed[0]?.id ?? null;
  const assessment = completed.find((a) => a.id === activeId) ?? null;
  // The check before this one (same Salesforce), for "since last check" changes.
  const previous = assessment ? completed.slice(completed.indexOf(assessment) + 1).find((a) => a.organizationName === assessment.organizationName) ?? null : null;
  const results = useAssessmentResults(activeId);
  const findingsQ = useFindings(activeId);

  const [view, setView] = useState<View>('dashboard');
  const type: ReportType = view === 'dashboard' ? 'executive' : view;
  const [range, setRange] = useState<Range>('12m');
  const [category, setCategory] = useState<'all' | CategoryId>('all');

  const findings = useMemo(() => (findingsQ.data ?? []).filter((f) => category === 'all' || f.categoryId === category), [findingsQ.data, category]);
  const history = useMemo(() => {
    const days = RANGE_DAYS[range];
    const cutoff = days ? Date.now() - days * 86_400_000 : null;
    return (list.data ?? [])
      .filter((a) => (cutoff ? new Date(a.completedAt ?? a.createdAt).getTime() >= cutoff : true))
      .filter((a) => category === 'all' || a.scope.categoryIds.includes(category));
  }, [list.data, range, category]);

  const sev = countBySeverity(findings);
  const affected = findings.reduce((a, f) => a + f.affectedRecords, 0);
  const scopeLabel = type === 'history' ? RANGE_LABEL[range] : category === 'all' ? 'All topics' : getCategory(category)!.name;

  const exportCsv = () => {
    if (!assessment) return;
    downloadBlob(new Blob(['﻿' + findingsCsv(findings)], { type: 'text/csv;charset=utf-8' }), `aquarient-findings-${slug(assessment.name)}.csv`);
    notify('Spreadsheet downloaded', `${findings.length} problems from ${assessment.name}.`, 'success');
  };

  // The browser's print dialog makes a pixel-perfect PDF of the branded report ("Save as PDF").
  const exportPdf = () => {
    if (view === 'dashboard') setView('executive');
    notify('Choose “Save as PDF”', `In the print dialog, pick “Save as PDF” as the printer to download ${REPORT_TITLES[type === 'executive' && view === 'dashboard' ? 'executive' : type]}.`, 'info');
    setTimeout(() => window.print(), 400);
  };

  const ready = !!assessment && !!results.data && !findingsQ.isLoading;

  return (
    <div>
      <PageHeader
        title="Reports"
        description="Print or download reports to share."
        actions={
          <>
            <Button icon={<Printer className="h-4 w-4" />} onClick={() => window.print()} disabled={!ready}>
              Print
            </Button>
            <Button icon={<FileSpreadsheet className="h-4 w-4" />} onClick={exportCsv} disabled={!ready || !findings.length}>
              Download spreadsheet (CSV)
            </Button>
            <Button variant="primary" icon={<FileDown className="h-4 w-4" />} onClick={exportPdf} disabled={!ready}>
              Download PDF
            </Button>
          </>
        }
      />

      {list.isLoading ? (
        <div className="card">
          <LoadingState rows={6} />
        </div>
      ) : list.error ? (
        <div className="card">
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        </div>
      ) : completed.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No reports yet"
            description="Run a health check to get your first report."
            action={
              <LinkButton to="/assessment" size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />}>
                Run a health check
              </LinkButton>
            }
          />
        </div>
      ) : (
        <>
          <KpiCards
            score={category === 'all' ? (results.data?.overallScore ?? null) : (results.data ? getCategoryScore(results.data, category) : null)}
            previousScore={category === 'all' ? (previous?.overallScore ?? null) : null}
            problems={findings.length}
            previousProblems={category === 'all' ? (previous?.findingsCount ?? null) : null}
            urgent={sev.critical + sev.high}
            records={affected}
            checks={history.length}
            trend={completed
              .filter((a) => a.organizationName === assessment?.organizationName && a.overallScore !== null)
              .slice(0, 12)
              .reverse()
              .map((a) => a.overallScore as number)}
          />

          <div className="no-print card mb-6">
            <div className="px-5 pt-2">
              <Tabs<View> layoutId="report-tabs" tabs={TABS} value={view} onChange={setView} />
            </div>
            <div className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
              <Select
                label="Which health check?"
                value={activeId ?? ''}
                onChange={setAssessmentId}
                className="lg:w-80"
                options={completed.map((a) => ({ value: a.id, label: `${a.name} · ${fmtDate(a.completedAt ?? a.createdAt)}` }))}
              />
              <Select<'all' | CategoryId>
                label="Topic"
                value={category}
                onChange={setCategory}
                className="lg:w-72"
                options={[{ value: 'all', label: 'All topics' }, ...CATEGORIES.map((c) => ({ value: c.id, label: c.name }))]}
              />
              <div className="flex items-center gap-2 lg:ml-auto">
                <Segmented<Range>
                  layoutId="range-seg"
                  value={range}
                  onChange={setRange}
                  options={[
                    { id: '30d', label: '30 days' },
                    { id: '90d', label: '90 days' },
                    { id: '12m', label: '12 months' },
                    { id: 'all', label: 'All time' },
                  ]}
                />
                <InfoTip align="end">The time period applies to the History report only.</InfoTip>
              </div>
            </div>
          </div>

          {results.isLoading || findingsQ.isLoading ? (
            <div className="card">
              <LoadingState rows={8} label="Building report…" />
            </div>
          ) : results.error || findingsQ.error ? (
            <div className="card">
              <ErrorState
                error={results.error ?? findingsQ.error}
                onRetry={() => {
                  results.refetch();
                  findingsQ.refetch();
                }}
              />
            </div>
          ) : view === 'proposal' && assessment ? (
            <ProposalReport assessment={assessment} />
          ) : view === 'dashboard' && assessment && results.data ? (
            <>
            <BenchmarkCard assessmentId={assessment.id} />
            <ReportDashboard assessment={assessment} results={results.data} findings={findings} history={list.data ?? []} category={category} onCategory={setCategory} />
            </>
          ) : (
            <ReportPreview
              type={type}
              assessment={assessment}
              results={results.data ?? null}
              findings={findings}
              history={type === 'history' ? history : history.filter((a) => a.organizationName === assessment?.organizationName)}
              scopeLabel={scopeLabel}
            />
          )}
        </>
      )}
    </div>
  );
}
