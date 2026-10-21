import { CheckCircle2, CircleDashed, Cloud, Play, Server, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { API_BASE_URL } from '@/api/client';
import { useApiHealth, useConnection } from '@/api/queries';
import { cx } from '@/lib/format';
import { LinkButton } from '../ui/Button';
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

/**
 * Onboarding checklist shown until a first assessment has completed.
 * Uses plain language so any user — technical or not — knows exactly what to do next.
 */
export function GettingStarted({ hasRunningAssessment }: { hasRunningAssessment?: boolean }) {
  const health = useApiHealth();
  const conn = useConnection();

  const apiState: StepState = health.isLoading ? 'checking' : health.data ? 'done' : 'current';
  const connected = conn.data?.status === 'connected';
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
        </div>
      </div>
    </section>
  );
}
