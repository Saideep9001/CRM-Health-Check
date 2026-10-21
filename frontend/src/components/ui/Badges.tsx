import { Ban, CheckCircle2, CircleDashed, Clock, Hourglass, XCircle } from 'lucide-react';
import type { ReactNode } from 'react';
import { cx } from '@/lib/format';
import { COVERAGE_LABEL, type CoverageStatus } from '@/lib/health';
import { URGENCY_HELP } from '@/config/glossary';
import type { AssessmentStatus, ConnectionStatus, FindingStatus, ReleaseStage, Severity } from '@/types';

export type Tone = 'neutral' | 'brand' | 'good' | 'warn' | 'bad' | 'accent';

const tones: Record<Tone, string> = {
  neutral: 'bg-muted text-ink-muted border-line',
  brand: 'bg-brand-soft text-brand-ink border-brand/20',
  good: 'bg-good-soft text-good border-good/20',
  warn: 'bg-warn-soft text-warn border-warn/20',
  bad: 'bg-bad-soft text-bad border-bad/20',
  accent: 'bg-accent-soft text-accent border-accent/20',
};

export function Badge({
  tone = 'neutral',
  icon,
  children,
  className,
  title,
}: {
  tone?: Tone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-4',
        tones[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export function ComingSoonBadge({ className }: { className?: string }) {
  return (
    <Badge tone="warn" icon={<Hourglass className="h-3 w-3" />} className={className} title="Visible now, can be checked in a later release">
      Coming Soon
    </Badge>
  );
}

/** Only flags what isn't ready yet; topics/areas that can be checked today show no badge. */
export function ReleaseBadge({ release }: { release: ReleaseStage }) {
  return release === 'coming-soon' ? <ComingSoonBadge /> : null;
}

export function CoverageBadge({ status }: { status: CoverageStatus }) {
  const tone: Record<CoverageStatus, Tone> = { 'not-assessed': 'neutral', partial: 'warn', assessed: 'good' };
  return <Badge tone={tone[status]}>{COVERAGE_LABEL[status]}</Badge>;
}

const sevTone: Record<Severity, string> = {
  critical: 'bg-sev-critical/10 text-sev-critical border-sev-critical/25',
  high: 'bg-sev-high/10 text-sev-high border-sev-high/25',
  medium: 'bg-sev-medium/10 text-sev-medium border-sev-medium/25',
  low: 'bg-sev-low/10 text-sev-low border-sev-low/25',
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      title={URGENCY_HELP[severity]}
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize leading-4',
        sevTone[severity],
      )}
    >
      <span className={cx('h-1.5 w-1.5 rounded-full bg-current', severity === 'critical' && 'animate-pulse')} />
      {severity}
    </span>
  );
}

export const FINDING_STATUS_LABEL: Record<FindingStatus, string> = {
  open: 'Open',
  'in-review': 'In Review',
  resolved: 'Resolved',
  'accepted-risk': 'Accepted Risk',
};

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  const tone: Record<FindingStatus, Tone> = { open: 'bad', 'in-review': 'brand', resolved: 'good', 'accepted-risk': 'neutral' };
  return <Badge tone={tone[status]}>{FINDING_STATUS_LABEL[status]}</Badge>;
}

export const ASSESSMENT_STATUS_LABEL: Record<AssessmentStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export function AssessmentStatusBadge({ status }: { status: AssessmentStatus }) {
  const map: Record<AssessmentStatus, { tone: Tone; icon: ReactNode }> = {
    queued: { tone: 'neutral', icon: <Clock className="h-3 w-3" /> },
    running: { tone: 'brand', icon: <CircleDashed className="h-3 w-3 animate-spin" /> },
    completed: { tone: 'good', icon: <CheckCircle2 className="h-3 w-3" /> },
    failed: { tone: 'bad', icon: <XCircle className="h-3 w-3" /> },
    cancelled: { tone: 'neutral', icon: <Ban className="h-3 w-3" /> },
  };
  return (
    <Badge tone={map[status].tone} icon={map[status].icon}>
      {ASSESSMENT_STATUS_LABEL[status]}
    </Badge>
  );
}

export const CONNECTION_STATUS_LABEL: Record<ConnectionStatus, string> = {
  disconnected: 'Disconnected',
  connected: 'Connected',
  expired: 'Session expired',
  error: 'Connection error',
};

export function ConnectionStatusBadge({ status }: { status: ConnectionStatus }) {
  const tone: Record<ConnectionStatus, Tone> = { disconnected: 'neutral', connected: 'good', expired: 'warn', error: 'bad' };
  return (
    <Badge tone={tone[status]} icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />}>
      {CONNECTION_STATUS_LABEL[status]}
    </Badge>
  );
}
