import { AlertOctagon, Inbox, RotateCw, ServerOff } from 'lucide-react';
import type { ReactNode } from 'react';
import { API_BASE_URL, errorMessage, isApiError } from '@/api/client';
import { cx } from '@/lib/format';
import { Button } from './Button';

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cx('relative overflow-hidden rounded-md bg-muted', className)}>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-surface/70 to-transparent" />
    </div>
  );
}

export function LoadingState({ rows = 5, label = 'Loading…' }: { rows?: number; label?: string }) {
  return (
    <div className="space-y-3 p-5" aria-busy="true" aria-label={label}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
}: {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx('flex flex-col items-center justify-center px-6 py-12 text-center', className)}>
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted text-ink-subtle">
        {icon ?? <Inbox className="h-6 w-6" />}
      </div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {description && <div className="mt-1 max-w-md text-sm text-ink-muted">{description}</div>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

/** Error state that distinguishes "backend unreachable" from request errors. */
export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const unavailable = isApiError(error) && error.isUnavailable;
  return (
    <EmptyState
      className={className}
      icon={unavailable ? <ServerOff className="h-6 w-6 text-warn" /> : <AlertOctagon className="h-6 w-6 text-bad" />}
      title={unavailable ? 'Backend service unavailable' : 'Something went wrong'}
      description={
        unavailable ? (
          <>
            {errorMessage(error)}
            <span className="mt-1 block text-xs text-ink-subtle">
              API endpoint: <code className="rounded bg-muted px-1">{API_BASE_URL}</code>
            </span>
          </>
        ) : (
          errorMessage(error)
        )
      }
      action={
        onRetry && (
          <Button size="sm" icon={<RotateCw className="h-3.5 w-3.5" />} onClick={onRetry}>
            Try again
          </Button>
        )
      }
    />
  );
}

/** Inline form error message. */
export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg border border-bad/25 bg-bad-soft px-3 py-2 text-sm text-bad">
      <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0" />
      {errorMessage(error)}
    </p>
  );
}
