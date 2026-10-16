import { AlarmClock, ArrowDownRight, ArrowUpRight, BellRing, Building2, CalendarClock, LayoutDashboard, Loader2, Mail, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { errorMessage } from '@/api/client';
import { useActivateOrg, useDeleteSchedule, usePortfolio, useRemoveOrg, useSaveSchedule, useTestAlertEmail } from '@/api/queries';
import { Badge } from '@/components/ui/Badges';
import { Button } from '@/components/ui/Button';
import { Field, Toggle } from '@/components/ui/Form';
import { Modal } from '@/components/ui/Overlay';
import { PageHeader, StaggerGrid, StaggerItem } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { Segmented } from '@/components/ui/Tabs';
import { ScoreRing, Sparkline } from '@/components/ui/Visuals';
import { useToast } from '@/context/ToastContext';
import { cx, fmtCompact, fmtDate, scoreBand } from '@/lib/format';
import type { PortfolioOrg, ScheduleFrequency } from '@/types';
import { ConnectModal } from './ConnectionPage';

const FREQ_LABEL: Record<ScheduleFrequency, string> = { daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly' };

function ScheduleModal({ org, onClose }: { org: PortfolioOrg; onClose: () => void }) {
  const s = org.schedule;
  const { notify } = useToast();
  const save = useSaveSchedule();
  const remove = useDeleteSchedule();
  const test = useTestAlertEmail();
  const [frequency, setFrequency] = useState<ScheduleFrequency>(s?.frequency ?? 'weekly');
  const [enabled, setEnabled] = useState(s?.enabled ?? true);
  const [email, setEmail] = useState(s?.alertEmail ?? '');
  const [drop, setDrop] = useState(s?.scoreDrop ?? 5);
  const [critical, setCritical] = useState(s?.alertNewCritical ?? true);

  const submit = () =>
    save.mutate(
      { orgId: org.orgId, body: { frequency, enabled, alertEmail: email.trim() || null, scoreDrop: drop, alertNewCritical: critical } },
      {
        onSuccess: (r) => {
          notify('Schedule saved', r.enabled && r.nextRunAt ? `Next check ${fmtDate(r.nextRunAt)}.` : 'Scheduled checks are paused.', 'success');
          onClose();
        },
        onError: (e) => notify('Couldn’t save the schedule', errorMessage(e), 'warning'),
      },
    );

  return (
    <Modal
      open
      onClose={onClose}
      title={`Scheduled checks · ${org.organizationName}`}
      description="Run a full health check automatically and get alerted when things get worse."
      footer={
        <>
          {s && (
            <Button variant="ghost" className="mr-auto" icon={<Trash2 className="h-4 w-4" />} onClick={() => remove.mutate(org.orgId, { onSuccess: onClose })}>
              Remove schedule
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save schedule'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <p className="mb-1.5 text-sm font-medium">How often</p>
          <Segmented<ScheduleFrequency>
            layoutId="freq-seg"
            value={frequency}
            onChange={setFrequency}
            options={[{ id: 'daily', label: 'Daily' }, { id: 'weekly', label: 'Weekly' }, { id: 'monthly', label: 'Monthly' }]}
          />
          <p className="mt-1 text-xs text-ink-subtle">Each run checks all 21 areas and uses a few hundred Salesforce API calls.</p>
        </div>
        <Toggle checked={enabled} onChange={setEnabled} label="Schedule is on" description="Pause it any time without losing the settings." />
        <div className="rounded-xl border border-line p-3">
          <p className="mb-2 flex items-center gap-2 text-sm font-semibold"><BellRing className="h-4 w-4 text-brand" /> Alerts</p>
          <Field label="Alert when the health score drops by" hint="Compared with the previous check of this org.">
            <div className="flex items-center gap-2">
              <input type="number" min={1} max={100} value={drop} onChange={(e) => setDrop(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} className="input w-24" />
              <span className="text-sm text-ink-muted">points or more</span>
            </div>
          </Field>
          <Toggle checked={critical} onChange={setCritical} label="Alert on new critical problems" description="Problems that weren’t there in the previous check." />
          <Field label="Also email alerts to (optional)" hint="Alerts always appear under the bell. Email needs SMTP set up on the server.">
            <div className="flex gap-2">
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" className="input" />
              <Button
                size="sm"
                icon={<Mail className="h-3.5 w-3.5" />}
                disabled={!s?.alertEmail || test.isPending}
                title={s?.alertEmail ? 'Send a test email' : 'Save an email address first'}
                onClick={() => test.mutate(org.orgId, { onSuccess: () => notify('Test email sent', s?.alertEmail ?? '', 'success'), onError: (e) => notify('Couldn’t send', errorMessage(e), 'warning') })}
              >
                Test
              </Button>
            </div>
          </Field>
        </div>
      </div>
    </Modal>
  );
}

function OrgCard({ org, onSchedule }: { org: PortfolioOrg; onSchedule: () => void }) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const activate = useActivateOrg();
  const remove = useRemoveOrg();
  const [reconnect, setReconnect] = useState(false);
  const connected = org.connectionStatus === 'connected';
  const delta = org.score !== null && org.previousScore !== null ? org.score - org.previousScore : null;
  const band = scoreBand(org.score);

  const open = (to: string) => {
    if (org.active) return navigate(to);
    activate.mutate(org.orgId, {
      onSuccess: () => {
        notify('Switched org', `You’re now working on ${org.organizationName}.`, 'success');
        navigate(to);
      },
      onError: (e) => notify('Couldn’t switch', errorMessage(e), 'warning'),
    });
  };

  return (
    <div className={cx('card flex h-full flex-col p-5', org.active && 'ring-2 ring-brand/40')}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-semibold" title={org.organizationName}>{org.organizationName}</h3>
            {org.active && <Badge tone="brand">Active</Badge>}
            {org.running && <Badge tone="accent"><Loader2 className="mr-1 inline h-3 w-3 animate-spin" />Checking</Badge>}
          </div>
          <p className="mt-0.5 text-xs text-ink-subtle">
            {[org.edition, org.environment === 'sandbox' ? 'Sandbox' : null].filter(Boolean).join(' · ') || org.orgId}
            {!connected && <span className="ml-1 font-medium text-warn">· {org.connectionStatus === 'expired' ? 'Connection expired' : 'Not connected'}</span>}
          </p>
        </div>
        <ScoreRing score={org.score} size={64} stroke={7} showBand={false} />
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg bg-muted/60 px-2 py-2">
          <p className="text-lg font-semibold tabular-nums">{org.openProblems}</p>
          <p className="text-[11px] text-ink-subtle">open problems</p>
        </div>
        <div className="rounded-lg bg-muted/60 px-2 py-2">
          <p className={cx('text-lg font-semibold tabular-nums', org.criticalProblems ? 'text-bad' : '')}>{org.criticalProblems}</p>
          <p className="text-[11px] text-ink-subtle">critical</p>
        </div>
        <div className="rounded-lg bg-muted/60 px-2 py-2" title="Value at risk on the biggest single problem (problems can overlap, so they aren’t added up)">
          <p className="text-lg font-semibold tabular-nums">{org.valueAtRisk ? fmtCompact(org.valueAtRisk) : '—'}</p>
          <p className="text-[11px] text-ink-subtle">biggest risk</p>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        {org.trend.length > 1 ? <Sparkline data={org.trend} color={band.color} /> : <span className="text-xs text-ink-subtle">Trend appears after two checks</span>}
        {delta !== null && delta !== 0 && (
          <span className={cx('inline-flex items-center text-xs font-semibold', delta > 0 ? 'text-good' : 'text-bad')}>
            {delta > 0 ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
            {delta > 0 ? '+' : ''}{delta}
          </span>
        )}
        <span className="ml-auto text-xs text-ink-subtle">{org.lastCheckedAt ? `Checked ${fmtDate(org.lastCheckedAt)}` : 'Never checked'}</span>
      </div>

      <button onClick={onSchedule} disabled={!connected} className="mt-3 flex items-center gap-2 rounded-lg border border-dashed border-line px-3 py-2 text-left text-xs transition hover:border-brand hover:text-brand disabled:opacity-50">
        <CalendarClock className="h-4 w-4 shrink-0" />
        {org.schedule?.enabled
          ? <span>{FREQ_LABEL[org.schedule.frequency]} checks · next {org.schedule.nextRunAt ? fmtDate(org.schedule.nextRunAt) : '—'}{org.schedule.alertEmail ? ` · alerts to ${org.schedule.alertEmail}` : ''}</span>
          : org.schedule ? <span>Scheduled checks paused</span> : <span>Schedule automatic checks and alerts</span>}
      </button>

      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        {connected ? (
          <>
            <Button size="sm" variant="primary" icon={<LayoutDashboard className="h-3.5 w-3.5" />} onClick={() => open('/dashboard')} disabled={activate.isPending}>
              {org.active ? 'Open' : 'Switch & open'}
            </Button>
            <Button size="sm" icon={<Play className="h-3.5 w-3.5" />} onClick={() => open('/assessment')} disabled={activate.isPending || org.running}>
              Run check
            </Button>
          </>
        ) : (
          <Button size="sm" variant="primary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => setReconnect(true)}>
            Reconnect
          </Button>
        )}
        {org.connectionStatus !== 'disconnected' && (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            icon={<Trash2 className="h-3.5 w-3.5" />}
            onClick={() => {
              if (window.confirm(`Disconnect ${org.organizationName}? Its past health checks are kept.`)) remove.mutate(org.orgId);
            }}
          >
            Disconnect
          </Button>
        )}
      </div>
      <ConnectModal open={reconnect} onClose={() => setReconnect(false)} />
    </div>
  );
}

export default function PortfolioPage() {
  const q = usePortfolio();
  const [adding, setAdding] = useState(false);
  const [scheduling, setScheduling] = useState<PortfolioOrg | null>(null);
  const orgs = q.data ?? [];
  const scored = orgs.filter((o) => o.score !== null);
  const avg = scored.length ? Math.round(scored.reduce((a, o) => a + (o.score ?? 0), 0) / scored.length) : null;
  const attention = scored.filter((o) => (o.score ?? 100) < 65).length;
  const critical = orgs.reduce((a, o) => a + o.criticalProblems, 0);
  const scheduled = orgs.filter((o) => o.schedule?.enabled).length;

  return (
    <div>
      <PageHeader
        title="Client portfolio"
        description="Every Salesforce org you look after: health, trend, risk and scheduled checks in one place."
        actions={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setAdding(true)}>Connect another org</Button>}
      />
      {q.isLoading ? (
        <div className="card"><LoadingState rows={6} label="Loading your orgs…" /></div>
      ) : q.error ? (
        <div className="card"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>
      ) : orgs.length === 0 ? (
        <div className="card">
          <EmptyState icon={<Building2 className="h-6 w-6" />} title="No orgs yet" description="Connect your first client’s Salesforce to start." action={<Button variant="primary" onClick={() => setAdding(true)}>Connect Salesforce</Button>} />
        </div>
      ) : (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
            {[
              { label: 'Orgs', value: orgs.length, icon: <Building2 className="h-4 w-4" /> },
              { label: 'Average score', value: avg ?? '—', icon: <LayoutDashboard className="h-4 w-4" /> },
              { label: 'Need attention', value: attention, icon: <AlarmClock className="h-4 w-4" />, bad: attention > 0 },
              { label: 'Critical problems', value: critical, icon: <BellRing className="h-4 w-4" />, bad: critical > 0 },
              { label: 'On a schedule', value: `${scheduled} of ${orgs.length}`, icon: <CalendarClock className="h-4 w-4" /> },
            ].map((k) => (
              <div key={k.label} className="card px-4 py-3">
                <p className="flex items-center gap-1.5 text-xs text-ink-muted">{k.icon}{k.label}</p>
                <p className={cx('mt-1 text-2xl font-semibold tabular-nums', k.bad && 'text-bad')}>{k.value}</p>
              </div>
            ))}
          </div>
          <StaggerGrid className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {orgs.map((o) => (
              <StaggerItem key={o.orgId}>
                <OrgCard org={o} onSchedule={() => setScheduling(o)} />
              </StaggerItem>
            ))}
          </StaggerGrid>
        </>
      )}
      <ConnectModal open={adding} onClose={() => setAdding(false)} />
      {scheduling && <ScheduleModal org={scheduling} onClose={() => setScheduling(null)} />}
    </div>
  );
}
