import { CloudOff, PlugZap } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useConnection, useRole } from '@/api/queries';
import { useLatestAssessment } from '@/hooks/useLatestAssessment';
import { fmtDate } from '@/lib/format';
import { LinkButton } from '../ui/Button';

/** Pages that show health check results. */
const RESULT_PAGES = /^\/(dashboard|results|assessment|reports)(\/|$)/;

/** While Salesforce isn't connected, say plainly that the numbers on screen are saved results, not live ones. */
export function SavedResultsBanner() {
  const { pathname } = useLocation();
  const conn = useConnection();
  const { latest } = useLatestAssessment();
  const { canEdit } = useRole();
  const status = conn.data?.status;
  if (!RESULT_PAGES.test(pathname) || !status || status === 'connected' || !latest) return null;

  const when = latest.completedAt ? fmtDate(latest.completedAt) : null;
  const why =
    status === 'expired' ? 'Your Salesforce connection has timed out.' : status === 'error' ? 'Salesforce can’t be reached right now.' : 'Salesforce is disconnected.';

  return (
    <div className="mb-5 flex flex-col gap-3 rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-sm sm:flex-row sm:items-center">
      <span className="flex min-w-0 flex-1 items-start gap-3">
        <CloudOff className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
        <span className="text-ink">
          <span className="font-semibold">{why}</span> You’re seeing <span className="font-semibold">saved results</span>
          {latest.organizationName ? ` for ${latest.organizationName}` : ''}
          {when ? ` from the check on ${when}` : ''} — nothing here is being read from Salesforce. Reconnect to run new checks and open live records.
        </span>
      </span>
      {canEdit && (
        <LinkButton to="/connection" size="sm" variant="primary" icon={<PlugZap className="h-3.5 w-3.5" />} className="shrink-0">
          {status === 'disconnected' ? 'Connect Salesforce' : 'Reconnect'}
        </LinkButton>
      )}
    </div>
  );
}
