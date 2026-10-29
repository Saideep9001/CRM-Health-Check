import { CheckCircle2, CircleDashed, Cloud, FileSpreadsheet, ListChecks, Play, Server, Table2, Upload, type LucideIcon } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { API_BASE_URL } from '@/api/client';
import { useApiHealth, useConnection, useRole } from '@/api/queries';
import { UploadDataModal } from '@/components/connection/UploadDataModal';
import { cx } from '@/lib/format';
import { Button, LinkButton } from '../ui/Button';
import { InfoTip } from '../ui/HelpTip';
import { HeroDots, RadarFrame } from './HealthHero';

type StepState = 'done' | 'current' | 'pending' | 'checking';

function Step({
  n,
  icon: Icon,
  title,
  text,
  state,
  action,
}: {
  n: number;
  icon: LucideIcon;
  title: string;
  text: ReactNode;
  state: StepState;
  action?: ReactNode;
}) {
  return (
    <li className={cx('flex gap-4 rounded-xl border p-4 transition-colors', state === 'current' ? 'border-brand/40 bg-brand-soft/60' : 'border-line')}>
      <span
        className={cx(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-full',
          state === 'done' ? 'bg-good-soft text-good' : state === 'current' ? 'bg-brand text-white' : 'bg-muted text-ink-subtle',
        )}
      >
        {state === 'done' ? (
          <CheckCircle2 className="h-5 w-5" />
        ) : state === 'checking' ? (
          <CircleDashed className="h-5 w-5 animate-spin" />
        ) : (
          <Icon className="h-[18px] w-[18px]" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">
          Step {n}: {title}
        </p>
        <div className="mt-0.5 text-sm text-ink-muted">{text}</div>
        {action && state === 'current' && <div className="mt-3">{action}</div>}
      </div>
    </li>
  );
}

/** One step of the file flow: a small numbered tile. */
function FileStep({ n, icon: Icon, title, text, state }: { n: number; icon: LucideIcon; title: string; text: string; state: StepState }) {
  return (
    <li className={cx('flex flex-1 items-start gap-3 rounded-xl border bg-surface p-3', state === 'current' ? 'border-brand/40' : 'border-line')}>
      <span className={cx('grid h-8 w-8 shrink-0 place-items-center rounded-full', state === 'done' ? 'bg-good-soft text-good' : state === 'current' ? 'bg-brand text-white' : 'bg-muted text-ink-subtle')}>
        {state === 'done' ? <CheckCircle2 className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold">{n}. {title}</span>
        <span className="block text-xs text-ink-muted">{text}</span>
      </span>
    </li>
  );
}

/** The other way in: no Salesforce sign-in, just a CSV or Excel export, checked with the same rules. */
function FileFlow({ hasRunningAssessment }: { hasRunningAssessment?: boolean }) {
  const conn = useConnection();
  const { canEdit } = useRole();
  const [open, setOpen] = useState(false);
  const uploaded = conn.data?.environment === 'upload' && conn.data.status === 'connected';
  return (
    <div className="mt-6 border-t border-dashed border-line pt-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-soft text-brand"><FileSpreadsheet className="h-4 w-4" /></span>
        <h3 className="text-base font-semibold">No Salesforce access? Check a file instead</h3>
        <span className="text-xs text-ink-subtle">A CSV or Excel export from Salesforce or any CRM — same checks, same rules.</span>
      </div>
      <ol className="mt-3 flex flex-col gap-2 sm:flex-row">
        <FileStep n={1} icon={Upload} title="Upload your file" state={uploaded ? 'done' : 'current'}
          text={uploaded ? `Using “${conn.data?.organizationName}”.` : 'Accounts, Contacts, Leads, Opportunities or others.'} />
        <FileStep n={2} icon={Table2} title="Match the columns" state={uploaded ? 'done' : 'pending'}
          text="Columns are matched to Salesforce fields; change any that are wrong." />
        <FileStep n={3} icon={ListChecks} title="Run the health check" state={uploaded ? 'current' : 'pending'}
          text={hasRunningAssessment ? 'A check is running now.' : 'Get a score and a list of fixes.'} />
      </ol>
      <div className="mt-3 flex flex-wrap gap-2">
        {uploaded ? (
          <>
            <LinkButton to="/assessment/data-quality" size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />}>Run the health check</LinkButton>
            <LinkButton to="/data" size="sm" icon={<Table2 className="h-3.5 w-3.5" />}>View the data</LinkButton>
            {canEdit && <Button size="sm" variant="ghost" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>Add another file</Button>}
          </>
        ) : (
          canEdit && <Button size="sm" variant="primary" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>Upload CSV or Excel</Button>
        )}
      </div>
      <UploadDataModal open={open} onClose={() => setOpen(false)}
        addTo={uploaded && conn.data?.orgId ? { orgId: conn.data.orgId, name: conn.data.organizationName ?? 'this upload' } : null} />
    </div>
  );
}

/**
 * Onboarding checklist shown until a first assessment has completed.
 * Uses plain language so any user — technical or not — knows exactly what to do next.
 */
export function GettingStarted({ hasRunningAssessment }: { hasRunningAssessment?: boolean }) {
  const health = useApiHealth();
  const conn = useConnection();

  const apiState: StepState = health.isLoading ? 'checking' : health.data ? 'done' : 'current';
  const connected = conn.data?.status === 'connected' && conn.data.environment !== 'upload'; // an upload is the file flow below
  const connState: StepState = apiState !== 'done' ? 'pending' : conn.isLoading ? 'checking' : connected ? 'done' : 'current';
  const runState: StepState = connState !== 'done' ? 'pending' : 'current';

  return (
    <section className="card relative overflow-hidden">
      <HeroDots />
      <div className="relative grid gap-8 p-6 md:grid-cols-[auto,1fr] md:items-center lg:p-8">
        <RadarFrame color="rgb(var(--brand))" dim>
          <div className="flex h-[164px] w-[164px] flex-col items-center justify-center rounded-full border-[12px] border-muted text-center">
            <span className="text-3xl font-semibold text-ink-subtle">—</span>
            <span className="text-[11px] font-medium text-ink-subtle">No score yet</span>
          </div>
        </RadarFrame>

        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight lg:text-2xl">
            Welcome! Let’s check your Salesforce
            <InfoTip size="md">Three quick steps to get your score and a list of what to fix.</InfoTip>
          </h2>

          <ol className="mt-5 space-y-3">
            {/* Step 1 — platform connectivity (technical prerequisite, explained plainly) */}
            <Step
              n={1}
              icon={Server}
              title="Platform ready"
              state={apiState}
              text={
                apiState === 'done' ? (
                  'The platform is ready.'
                ) : apiState === 'checking' ? (
                  'Checking…'
                ) : (
                  <>
                    The platform isn’t available right now.{' '}
                    <span className="text-ink">Please contact your administrator</span> (
                    <code className="rounded bg-muted px-1 text-xs">{API_BASE_URL}</code>).
                  </>
                )
              }
            />

            {/* Step 2 — Salesforce OAuth (explain in plain terms what happens) */}
            <Step
              n={2}
              icon={Cloud}
              title="Connect your Salesforce"
              state={connState}
              text={
                connected
                  ? `Connected to ${conn.data?.organizationName}.`
                  : 'Sign in on Salesforce’s own page. We only read your data.'
              }
              action={
                <LinkButton to="/connection" size="sm" variant="primary" icon={<Cloud className="h-3.5 w-3.5" />}>
                  Connect my Salesforce
                </LinkButton>
              }
            />

            {/* Step 3 — run the check */}
            <Step
              n={3}
              icon={Play}
              title="Run your first health check"
              state={runState}
              text={
                hasRunningAssessment
                  ? 'A check is running. Results will show here when done.'
                  : 'Press start and get results in minutes.'
              }
              action={
                hasRunningAssessment ? (
                  <LinkButton to="/history" size="sm">
                    Watch progress
                  </LinkButton>
                ) : (
                  <LinkButton to="/assessment" size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />}>
                    Start my first health check
                  </LinkButton>
                )
              }
            />
          </ol>

          <FileFlow hasRunningAssessment={hasRunningAssessment} />
        </div>
      </div>
    </section>
  );
}
