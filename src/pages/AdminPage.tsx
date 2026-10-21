import { Activity, Building2, Check, Inbox, KeyRound, Lock, MonitorSmartphone, ShieldCheck, ShieldOff, Users, X } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { errorMessage } from '@/api/client';
import { useAccessRequests, useAdminOverview, useAuditLog, useDecideRequest, usePortfolio, useRole } from '@/api/queries';
import { TeamSettings } from '@/components/settings/TeamSettings';
import { Badge } from '@/components/ui/Badges';
import { Button, LinkButton } from '@/components/ui/Button';
import { Field, Select, Toggle } from '@/components/ui/Form';
import { Modal } from '@/components/ui/Overlay';
import { PageHeader, SectionCard } from '@/components/ui/Page';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/States';
import { Tabs } from '@/components/ui/Tabs';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDateTime } from '@/lib/format';
import type { AccessRequest, AuditEvent, UserRole } from '@/types';

type Tab = 'people' | 'requests' | 'activity';

const ROLE_LABEL: Record<string, string> = { admin: 'Admin', consultant: 'Consultant', viewer: 'Viewer' };

const ACTION_LABEL: Record<string, string> = {
  'signed.in': 'Signed in',
  'account.locked': 'Account locked',
  'account.unlocked': 'Account unlocked',
  'password.changed': 'Changed their password',
  'password.reset': 'Reset a password',
  'user.added': 'Added a person',
  'user.updated': 'Changed access',
  'user.signed_out': 'Signed someone out',
  'request.created': 'Asked for access',
  'request.approved': 'Approved a request',
  'request.rejected': 'Rejected a request',
};

function Stat({ icon, label, value, tone, hint }: { icon: ReactNode; label: string; value: number | undefined; tone?: 'warn' | 'brand'; hint?: string }) {
  return (
    <div className="card flex items-center gap-3 p-4" title={hint}>
      <span className={cx('grid h-10 w-10 shrink-0 place-items-center rounded-xl', tone === 'warn' && value ? 'bg-warn-soft text-warn' : tone === 'brand' && value ? 'bg-brand-soft text-brand' : 'bg-muted text-ink-muted')}>
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-2xl font-semibold leading-none tabular-nums">{value ?? '—'}</p>
        <p className="mt-1 truncate text-xs text-ink-muted">{label}</p>
      </div>
    </div>
  );
}

function asked(r: AccessRequest) {
  return r.kind === 'org' ? (
    <>Access to a client org: <span className="font-medium text-ink">“{r.orgNote}”</span></>
  ) : (
    <>Role change: <span className="font-medium text-ink">{ROLE_LABEL[r.userRole] ?? r.userRole} → {ROLE_LABEL[r.requestedRole ?? ''] ?? r.requestedRole}</span></>
  );
}

function DecideModal({ request, approve, onClose }: { request: AccessRequest; approve: boolean; onClose: () => void }) {
  const decide = useDecideRequest();
  const orgs = usePortfolio();
  const { notify } = useToast();
  const [orgIds, setOrgIds] = useState<string[]>([]);
  const [allOrgs, setAllOrgs] = useState(false);
  const [role, setRole] = useState<UserRole>((request.requestedRole as UserRole) ?? 'consultant');
  const [note, setNote] = useState('');
  const needsOrgs = approve && request.kind === 'org' && !allOrgs && orgIds.length === 0;

  const submit = () =>
    decide.mutate(
      { id: request.id, approve, note: note.trim() || undefined, ...(approve && request.kind === 'org' ? { orgIds, allOrgs } : {}), ...(approve && request.kind === 'role' ? { role } : {}) },
      {
        onSuccess: () => {
          notify(approve ? 'Request approved' : 'Request rejected', approve ? `${request.userName} has the new access now.` : undefined, approve ? 'success' : 'info');
          onClose();
        },
      },
    );

  return (
    <Modal
      open
      onClose={onClose}
      title={approve ? `Approve ${request.userName}’s request` : `Reject ${request.userName}’s request`}
      description={request.userEmail}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant={approve ? 'primary' : 'danger'} onClick={submit} disabled={decide.isPending || needsOrgs}>
            {decide.isPending ? 'Saving…' : approve ? 'Approve' : 'Reject'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="rounded-lg bg-muted px-3 py-2 text-sm text-ink-muted">{asked(request)}{request.message && <span className="mt-1 block italic">“{request.message}”</span>}</p>
        {approve && request.kind === 'org' && (
          <div>
            <p className="mb-1 text-sm font-medium">Which client orgs should they get?</p>
            <Toggle checked={allOrgs} onChange={setAllOrgs} label="Every org" description="Including orgs connected later." />
            {!allOrgs && (
              <div className="mt-1 max-h-48 space-y-1 overflow-y-auto rounded-lg border border-line p-2">
                {orgs.isLoading && <LoadingState rows={2} />}
                {(orgs.data ?? []).length === 0 && !orgs.isLoading && <p className="px-1 py-2 text-xs text-ink-subtle">No orgs connected yet.</p>}
                {(orgs.data ?? []).map((o) => (
                  <label key={o.orgId} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-muted">
                    <input
                      type="checkbox"
                      checked={orgIds.includes(o.orgId)}
                      onChange={(e) => setOrgIds(e.target.checked ? [...orgIds, o.orgId] : orgIds.filter((x) => x !== o.orgId))}
                      className="h-4 w-4 accent-[rgb(var(--brand))]"
                    />
                    {o.organizationName}
                  </label>
                ))}
              </div>
            )}
          </div>
        )}
        {approve && request.kind === 'role' && (
          <Field label="Give them this role">
            <Select<UserRole> label="Role" value={role} onChange={setRole} options={(['consultant', 'viewer', 'admin'] as UserRole[]).map((r) => ({ value: r, label: ROLE_LABEL[r] }))} />
          </Field>
        )}
        <Field label={approve ? 'Note (optional)' : 'Reason (optional)'} hint="They’ll see this with their request.">
          <input className="input" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {decide.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(decide.error)}</p>}
      </div>
    </Modal>
  );
}

function RequestsPanel() {
  const [show, setShow] = useState<'pending' | 'all'>('pending');
  const list = useAccessRequests(show === 'pending' ? 'pending' : undefined);
  const [deciding, setDeciding] = useState<{ request: AccessRequest; approve: boolean } | null>(null);

  return (
    <SectionCard
      title="Access requests"
      description="People ask for another client org or a different role from Settings → Team & Access. Approving applies straight away."
      actions={
        <div className="flex rounded-lg border border-line p-0.5 text-xs">
          {(['pending', 'all'] as const).map((v) => (
            <button key={v} onClick={() => setShow(v)} className={cx('rounded-md px-2.5 py-1 font-medium', show === v ? 'bg-brand-soft text-brand-ink' : 'text-ink-muted hover:text-ink')}>
              {v === 'pending' ? 'Waiting' : 'All'}
            </button>
          ))}
        </div>
      }
      bodyClassName="p-0"
    >
      {list.isLoading ? (
        <div className="p-5"><LoadingState rows={3} /></div>
      ) : list.error ? (
        <div className="p-5"><ErrorState error={list.error} onRetry={() => list.refetch()} /></div>
      ) : !list.data?.length ? (
        <EmptyState
          className="py-10"
          icon={<Inbox className="h-6 w-6" />}
          title={show === 'pending' ? 'No requests waiting' : 'No requests yet'}
          description="When someone asks for more access, it appears here for you to approve or reject."
        />
      ) : (
        <ul className="divide-y divide-line">
          {list.data.map((r) => (
            <li key={r.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {r.userName} <span className="text-xs font-normal text-ink-subtle">{r.userEmail} · {ROLE_LABEL[r.userRole] ?? r.userRole}</span>
                </p>
                <p className="mt-0.5 text-sm text-ink-muted">{asked(r)}</p>
                {r.message && <p className="mt-0.5 text-sm italic text-ink-muted">“{r.message}”</p>}
                <p className="mt-1 text-xs text-ink-subtle">
                  Asked {r.createdAt ? fmtDateTime(r.createdAt) : ''}
                  {r.status !== 'pending' && r.decidedBy && ` · ${r.status} by ${r.decidedBy.replace(/\s*<.*>$/, '')}${r.decidedAt ? ` on ${fmtDateTime(r.decidedAt)}` : ''}`}
                  {r.decisionNote && ` — “${r.decisionNote}”`}
                </p>
              </div>
              {r.status === 'pending' ? (
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" icon={<X className="h-3.5 w-3.5" />} onClick={() => setDeciding({ request: r, approve: false })}>Reject</Button>
                  <Button size="sm" variant="primary" icon={<Check className="h-3.5 w-3.5" />} onClick={() => setDeciding({ request: r, approve: true })}>Approve</Button>
                </div>
              ) : (
                <Badge tone={r.status === 'approved' ? 'good' : r.status === 'rejected' ? 'bad' : 'neutral'} className="self-start capitalize sm:self-center">{r.status}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
      {deciding && <DecideModal request={deciding.request} approve={deciding.approve} onClose={() => setDeciding(null)} />}
    </SectionCard>
  );
}

function ActivityPanel() {
  const log = useAuditLog();
  const name = (who: string | null) => (who ?? '').replace(/\s*<(.+)>$/, '');
  const email = (who: string | null) => (who ?? '').match(/<(.+)>$/)?.[1] ?? '';
  return (
    <SectionCard title="Activity log" description="Sign-ins and every change to people, roles and access — newest first." bodyClassName="p-0">
      {log.isLoading ? (
        <div className="p-5"><LoadingState rows={4} /></div>
      ) : log.error ? (
        <div className="p-5"><ErrorState error={log.error} onRetry={() => log.refetch()} /></div>
      ) : !log.data?.length ? (
        <EmptyState className="py-10" icon={<Activity className="h-6 w-6" />} title="Nothing yet" description="Sign-ins and access changes will be listed here." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <thead className="bg-muted/50 text-left text-[11px] uppercase tracking-wide text-ink-subtle">
              <tr>
                <th className="px-5 py-2">When</th>
                <th className="px-3 py-2">Who</th>
                <th className="px-3 py-2">What</th>
                <th className="px-5 py-2">Details</th>
              </tr>
            </thead>
            <tbody>
              {log.data.map((e: AuditEvent) => (
                <tr key={e.id} className="border-t border-line align-top">
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs text-ink-muted">{e.at ? fmtDateTime(e.at) : ''}</td>
                  <td className="px-3 py-2.5">
                    <p className="font-medium">{name(e.actor)}</p>
                    <p className="text-xs text-ink-subtle">{email(e.actor)}</p>
                  </td>
                  <td className="px-3 py-2.5">{ACTION_LABEL[e.action] ?? e.action}</td>
                  <td className="px-5 py-2.5 text-xs text-ink-muted">
                    {e.target && e.target !== e.actor && <span className="font-medium text-ink">{name(e.target)} </span>}
                    {e.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}

export default function AdminPage() {
  const { isAdmin, loading } = useRole();
  const overview = useAdminOverview(isAdmin);
  const [params, setParams] = useSearchParams();
  const tab = ((['people', 'requests', 'activity'] as Tab[]).find((t) => t === params.get('tab')) ?? 'people') as Tab;

  if (loading) return <LoadingState rows={4} />;
  if (!isAdmin) {
    return (
      <EmptyState
        className="py-20"
        icon={<ShieldOff className="h-7 w-7" />}
        title="Admins only"
        description="The Admin Panel is only available to admins. If you need more access, ask for it in Settings → Team & Access."
        action={<LinkButton to="/settings?tab=team" variant="primary">Ask for access</LinkButton>}
      />
    );
  }

  const o = overview.data;
  const pending = o?.pendingRequests ?? 0;
  const tabs = [
    { id: 'people' as Tab, label: 'People & permissions', icon: <Users className="h-4 w-4" /> },
    { id: 'requests' as Tab, label: 'Access requests', icon: <Inbox className="h-4 w-4" />, count: pending || undefined },
    { id: 'activity' as Tab, label: 'Activity log', icon: <Activity className="h-4 w-4" /> },
  ];

  return (
    <div>
      <PageHeader
        eyebrow={<Badge tone="brand" icon={<ShieldCheck className="h-3 w-3" />}>Admins only</Badge>}
        title="Admin Panel"
        description="Manage who can sign in, their role, which client orgs they see, and approve or reject requests for more access."
      />

      {overview.error ? (
        <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
      ) : (
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <Stat icon={<Users className="h-5 w-5" />} label={o ? `People · ${o.admins} admin${o.admins === 1 ? '' : 's'}` : 'People'} value={o ? o.users - o.deactivated : undefined} hint={o ? `${o.consultants} consultants, ${o.viewers} viewers, ${o.deactivated} deactivated` : undefined} />
          <Stat icon={<Inbox className="h-5 w-5" />} label="Requests waiting" value={o?.pendingRequests} tone="brand" />
          <Stat icon={<Lock className="h-5 w-5" />} label="Locked accounts" value={o?.locked} tone="warn" hint="Locked for 15 minutes after 5 wrong passwords. You can unlock them." />
          <Stat icon={<KeyRound className="h-5 w-5" />} label="Must set password" value={o?.mustChangePassword} tone="warn" hint="Still on a default or temporary password." />
          <Stat icon={<Building2 className="h-5 w-5" />} label="Client orgs" value={o?.orgsConnected} />
          <Stat icon={<MonitorSmartphone className="h-5 w-5" />} label="Signed-in sessions" value={o?.activeSessions} />
        </div>
      )}

      <div className="card mb-6 px-5 pt-2">
        <Tabs<Tab> layoutId="admin-tabs" tabs={tabs} value={tab} onChange={(t) => setParams({ tab: t }, { replace: true })} />
      </div>

      {tab === 'people' && <TeamSettings />}
      {tab === 'requests' && <RequestsPanel />}
      {tab === 'activity' && <ActivityPanel />}
    </div>
  );
}
