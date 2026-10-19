import { KeyRound, Plus, ShieldCheck, UserCheck, UserX } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { errorMessage } from '@/api/client';
import { useChangePassword, useCreateMember, useMe, usePortfolio, useResetMemberPassword, useTeam, useUpdateMember } from '@/api/queries';
import { Badge } from '@/components/ui/Badges';
import { Button } from '@/components/ui/Button';
import { Field, Select, Toggle } from '@/components/ui/Form';
import { Modal } from '@/components/ui/Overlay';
import { SectionCard } from '@/components/ui/Page';
import { ErrorState, LoadingState } from '@/components/ui/States';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDateTime } from '@/lib/format';
import type { TeamMember, UserRole } from '@/types';

const ROLE_LABEL: Record<UserRole, string> = { admin: 'Admin', consultant: 'Consultant', viewer: 'Viewer' };
const ROLE_HELP: Record<UserRole, string> = {
  admin: 'Everything: all orgs, team, Salesforce app keys and report branding.',
  consultant: 'Connects orgs, runs checks, tracks fixes and schedules — for their orgs.',
  viewer: 'Read-only: sees results, reports and data for their orgs.',
};

/** A random temporary password the admin can pass on (the person changes it after signing in). */
function tempPassword() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
  const bytes = new Uint32Array(14);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => chars[b % chars.length]).join('');
}

function OrgPicker({ allOrgs, orgIds, onChange, disabled }: { allOrgs: boolean; orgIds: string[]; onChange: (all: boolean, ids: string[]) => void; disabled?: boolean }) {
  const orgs = usePortfolio();
  return (
    <div>
      <Toggle checked={allOrgs} onChange={(v) => onChange(v, orgIds)} label="Access to every org" description="Including orgs connected later." />
      {!allOrgs && (
        <div className="mt-1 max-h-44 space-y-1 overflow-y-auto rounded-lg border border-line p-2">
          {(orgs.data ?? []).length === 0 && <p className="px-1 py-2 text-xs text-ink-subtle">No orgs connected yet.</p>}
          {(orgs.data ?? []).map((o) => (
            <label key={o.orgId} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-muted">
              <input
                type="checkbox"
                disabled={disabled}
                checked={orgIds.includes(o.orgId)}
                onChange={(e) => onChange(false, e.target.checked ? [...orgIds, o.orgId] : orgIds.filter((x) => x !== o.orgId))}
                className="h-4 w-4 accent-[rgb(var(--brand))]"
              />
              {o.organizationName}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function AddMemberModal({ onClose }: { onClose: () => void }) {
  const create = useCreateMember();
  const { notify } = useToast();
  const [form, setForm] = useState({ name: '', email: '', role: 'consultant' as UserRole, allOrgs: false, orgIds: [] as string[], password: tempPassword() });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(form, {
      onSuccess: (m) => {
        notify('Person added', `Share the temporary password with ${m.name} securely (not by email with their address in it).`, 'success');
        onClose();
      },
    });
  };
  return (
    <Modal
      open
      onClose={onClose}
      title="Add a person"
      description="They sign in with their email and this temporary password, then change it under Settings → Profile."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="add-member" disabled={create.isPending}>{create.isPending ? 'Adding…' : 'Add person'}</Button>
        </>
      }
    >
      <form id="add-member" onSubmit={submit} className="space-y-3" noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><input className="input" value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus /></Field>
          <Field label="Work email"><input type="email" className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        </div>
        <Field label="Role" hint={ROLE_HELP[form.role]}>
          <Select<UserRole> label="Role" value={form.role} onChange={(role) => setForm({ ...form, role })} options={(['consultant', 'viewer', 'admin'] as UserRole[]).map((r) => ({ value: r, label: ROLE_LABEL[r] }))} />
        </Field>
        {form.role !== 'admin' && <OrgPicker allOrgs={form.allOrgs} orgIds={form.orgIds} onChange={(allOrgs, orgIds) => setForm({ ...form, allOrgs, orgIds })} />}
        <Field label="Temporary password" hint="At least 10 characters. Copy it now — it isn’t shown again.">
          <div className="flex gap-2">
            <input className="input font-mono" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <Button type="button" size="sm" onClick={() => setForm({ ...form, password: tempPassword() })}>New</Button>
          </div>
        </Field>
        {create.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(create.error)}</p>}
      </form>
    </Modal>
  );
}

function EditMemberModal({ member, isMe, onClose }: { member: TeamMember; isMe: boolean; onClose: () => void }) {
  const update = useUpdateMember();
  const reset = useResetMemberPassword();
  const { notify } = useToast();
  const [role, setRole] = useState<UserRole>(member.role);
  const [allOrgs, setAllOrgs] = useState(member.allOrgs);
  const [orgIds, setOrgIds] = useState(member.orgIds);
  const [newPassword, setNewPassword] = useState<string | null>(null);
  const save = () =>
    update.mutate(
      { id: member.id, body: { role, allOrgs, orgIds } },
      { onSuccess: () => { notify('Access updated', isMe ? undefined : `${member.name} will see the change at their next sign-in.`, 'success'); onClose(); } },
    );
  return (
    <Modal
      open
      onClose={onClose}
      title={member.name}
      description={member.email}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={update.isPending}>{update.isPending ? 'Saving…' : 'Save'}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Role" hint={ROLE_HELP[role]}>
          <Select<UserRole> label="Role" value={role} onChange={setRole} options={(['admin', 'consultant', 'viewer'] as UserRole[]).map((r) => ({ value: r, label: ROLE_LABEL[r] }))} />
        </Field>
        {role !== 'admin' && <OrgPicker allOrgs={allOrgs} orgIds={orgIds} onChange={(a, ids) => { setAllOrgs(a); setOrgIds(ids); }} />}
        {update.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(update.error)}</p>}
        {!isMe && (
          <div className="rounded-lg border border-line p-3">
            <p className="text-sm font-medium">Reset password</p>
            {newPassword ? (
              <p className="mt-1 text-sm">New temporary password: <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{newPassword}</code> — they’ve been signed out everywhere.</p>
            ) : (
              <Button
                size="sm"
                className="mt-2"
                icon={<KeyRound className="h-3.5 w-3.5" />}
                disabled={reset.isPending}
                onClick={() => {
                  const pw = tempPassword();
                  reset.mutate({ id: member.id, password: pw }, { onSuccess: () => setNewPassword(pw), onError: (e) => notify('Couldn’t reset', errorMessage(e), 'warning') });
                }}
              >
                Create a temporary password
              </Button>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}

/** Admins: who can sign in, their role, and which client orgs they see. */
export function TeamSettings() {
  const team = useTeam();
  const me = useMe();
  const update = useUpdateMember();
  const orgs = usePortfolio();
  const { notify } = useToast();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<TeamMember | null>(null);
  const orgName = new Map((orgs.data ?? []).map((o) => [o.orgId, o.organizationName]));

  return (
    <SectionCard
      title="Team & access"
      description="Admins see everything. Consultants and viewers only see the orgs you give them."
      actions={<Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAdding(true)}>Add person</Button>}
      bodyClassName="p-0"
    >
      {team.isLoading ? (
        <div className="p-5"><LoadingState rows={3} /></div>
      ) : team.error ? (
        <div className="p-5"><ErrorState error={team.error} onRetry={() => team.refetch()} /></div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-muted/50 text-left text-[11px] uppercase tracking-wide text-ink-subtle">
              <tr>
                <th className="px-5 py-2">Person</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Orgs</th>
                <th className="px-3 py-2">Last sign-in</th>
                <th className="px-5 py-2 text-right" />
              </tr>
            </thead>
            <tbody>
              {(team.data ?? []).map((m) => {
                const isMe = m.id === me.data?.id;
                return (
                  <tr key={m.id} className={cx('border-t border-line', !m.isActive && 'opacity-60')}>
                    <td className="px-5 py-3">
                      <p className="font-medium">{m.name}{isMe && <span className="ml-1.5 text-xs text-ink-subtle">(you)</span>}</p>
                      <p className="text-xs text-ink-subtle">{m.email}</p>
                    </td>
                    <td className="px-3 py-3">
                      <Badge tone={m.role === 'admin' ? 'brand' : m.role === 'consultant' ? 'accent' : 'neutral'}>{ROLE_LABEL[m.role]}</Badge>
                      {!m.isActive && <Badge tone="warn" className="ml-1">Deactivated</Badge>}
                    </td>
                    <td className="px-3 py-3 text-xs text-ink-muted">
                      {m.allOrgs ? 'All orgs' : m.orgIds.length ? m.orgIds.map((id) => orgName.get(id) ?? id).join(', ') : <span className="text-warn">None yet</span>}
                    </td>
                    <td className="px-3 py-3 text-xs text-ink-muted">{m.lastLoginAt ? fmtDateTime(m.lastLoginAt) : 'Never'}</td>
                    <td className="whitespace-nowrap px-5 py-3 text-right">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(m)}>Edit</Button>
                      {!isMe && (
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={m.isActive ? <UserX className="h-3.5 w-3.5" /> : <UserCheck className="h-3.5 w-3.5" />}
                          onClick={() => update.mutate({ id: m.id, body: { isActive: !m.isActive } }, { onError: (e) => notify('Couldn’t change', errorMessage(e), 'warning') })}
                        >
                          {m.isActive ? 'Deactivate' : 'Reactivate'}
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {adding && <AddMemberModal onClose={() => setAdding(false)} />}
      {editing && <EditMemberModal member={editing} isMe={editing.id === me.data?.id} onClose={() => setEditing(null)} />}
    </SectionCard>
  );
}

/** Change your own password (signs you out on other devices). */
export function ChangePasswordCard() {
  const change = useChangePassword();
  const { notify } = useToast();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const mismatch = !!confirm && confirm !== next;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (mismatch || next.length < 10) return;
    change.mutate(
      { currentPassword: current, newPassword: next },
      { onSuccess: () => { notify('Password changed', 'You’ve been signed out on other devices.', 'success'); setCurrent(''); setNext(''); setConfirm(''); } },
    );
  };
  return (
    <SectionCard title={<span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-4 w-4 text-good" /> Change password</span>}>
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-3" noValidate>
        <Field label="Current password"><input type="password" autoComplete="current-password" className="input" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
        <Field label="New password" hint="At least 10 characters."><input type="password" autoComplete="new-password" className="input" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <Field label="Confirm new password">
          <input type="password" autoComplete="new-password" className={cx('input', mismatch && 'border-bad')} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          {mismatch && <span className="mt-1 block text-xs text-bad">Passwords don’t match</span>}
        </Field>
        <div className="sm:col-span-3">
          {change.error && <p className="mb-2 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(change.error)}</p>}
          <Button type="submit" variant="primary" disabled={!current || next.length < 10 || mismatch || change.isPending}>
            {change.isPending ? 'Saving…' : 'Change password'}
          </Button>
        </div>
      </form>
    </SectionCard>
  );
}
