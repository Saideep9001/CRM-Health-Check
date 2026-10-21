import { Bell, Building2, Check, Cloud, Lock, Monitor, Moon, Palette, Save, ShieldCheck, Sparkles, Sun, User, Users } from 'lucide-react';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { API_BASE_URL } from '@/api/client';
import { useApiHealth, useAuthStatus, useConnection, useMe, useRole, useSettings, useUpdateMe, useUpdateSettings } from '@/api/queries';
import { ChangePasswordCard, RequestAccessCard } from '@/components/settings/TeamSettings';
import { ConnectionStatusBadge } from '@/components/ui/Badges';
import { Button } from '@/components/ui/Button';
import { Field, Select, Toggle } from '@/components/ui/Form';
import { InfoTip } from '@/components/ui/HelpTip';
import { PageHeader, SectionCard } from '@/components/ui/Page';
import { ConsultingSettings } from '@/components/settings/ConsultingSettings';
import { ErrorState, InlineError, LoadingState } from '@/components/ui/States';
import { Tabs } from '@/components/ui/Tabs';
import { useTheme, type ThemePref } from '@/context/ThemeContext';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDateTime } from '@/lib/format';
import type { AppSettings, NotificationPreferences, UserProfile } from '@/types';

type Tab = 'preferences' | 'profile' | 'notifications' | 'branding' | 'team' | 'security' | 'organizations';
const TABS: { id: Tab; label: string; icon: ReactNode }[] = [
  { id: 'preferences', label: 'Application Preferences', icon: <Palette className="h-4 w-4" /> },
  { id: 'profile', label: 'Profile Information', icon: <User className="h-4 w-4" /> },
  { id: 'notifications', label: 'Notification Preferences', icon: <Bell className="h-4 w-4" /> },
  { id: 'branding', label: 'Report Branding', icon: <Sparkles className="h-4 w-4" /> },
  { id: 'team', label: 'Team & Access', icon: <Users className="h-4 w-4" /> },
  { id: 'security', label: 'Security Information', icon: <Lock className="h-4 w-4" /> },
  { id: 'organizations', label: 'Connected Organizations', icon: <Building2 className="h-4 w-4" /> },
];

function ThemeCard({ id, label, icon, active, onClick }: { id: ThemePref; label: string; icon: ReactNode; active: boolean; onClick: () => void }) {
  const dark = id === 'dark';
  return (
    <button onClick={onClick} aria-pressed={active} className={cx('rounded-xl border-2 p-2 text-left transition', active ? 'border-brand' : 'border-line hover:border-ink-subtle/40')}>
      <div className={cx('relative h-24 overflow-hidden rounded-lg', id === 'system' ? 'bg-gradient-to-r from-slate-100 from-50% to-slate-900 to-50%' : dark ? 'bg-slate-900' : 'bg-slate-100')}>
        <div className={cx('absolute bottom-0 left-0 top-0 w-8', dark ? 'bg-slate-800' : 'bg-white')} />
        <div className={cx('absolute left-11 right-3 top-3 h-3 rounded', dark ? 'bg-slate-700' : 'bg-white')} />
        <div className={cx('absolute left-11 top-9 h-10 w-14 rounded', dark || id === 'system' ? 'bg-slate-700' : 'bg-white')} />
        <div className="absolute right-3 top-9 h-10 w-14 rounded bg-blue-500/80" />
      </div>
      <div className="mt-2 flex items-center justify-between px-1">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          {icon}
          {label}
        </span>
        {active && (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand text-white">
            <Check className="h-3 w-3" />
          </span>
        )}
      </div>
    </button>
  );
}

function ProfileForm({ me }: { me: UserProfile }) {
  const update = useUpdateMe();
  const { notify } = useToast();
  const [form, setForm] = useState({ name: me.name, title: me.title ?? '' });
  useEffect(() => setForm({ name: me.name, title: me.title ?? '' }), [me]);

  const errors = { name: !form.name.trim() ? 'Name is required' : null };
  const dirty = form.name !== me.name || form.title !== (me.title ?? '');
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (errors.name) return;
    update.mutate({ name: form.name.trim(), title: form.title.trim() || null }, { onSuccess: () => notify('Profile saved', undefined, 'success') });
  };

  return (
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
      <Field label="Email" hint="Your sign-in email. An admin can change it.">
        <input className="input" value={me.email} disabled />
      </Field>
      <Field label="Role" hint="Set by an admin under Team & Access.">
        <input className="input capitalize" value={me.role ?? ''} disabled />
      </Field>
      {(
        [
          ['name', 'Full name', 'text'],
          ['title', 'Job title', 'text'],
        ] as const
      ).map(([k, label, type]) => (
        <Field key={k} label={label}>
          <input
            type={type}
            className={cx('input', k in errors && errors[k as keyof typeof errors] && 'border-bad')}
            value={form[k]}
            maxLength={120}
            onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
          />
          {k in errors && errors[k as keyof typeof errors] && <span className="mt-1 block text-xs text-bad">{errors[k as keyof typeof errors]}</span>}
        </Field>
      ))}
      <div className="space-y-3 sm:col-span-2">
        <InlineError error={update.error} />
        <Button type="submit" variant="primary" icon={<Save className="h-4 w-4" />} disabled={!dirty || update.isPending}>
          {update.isPending ? 'Saving…' : 'Save profile'}
        </Button>
      </div>
    </form>
  );
}

function SettingsForm({ settings, section }: { settings: AppSettings; section: 'general' | 'notifications' }) {
  const update = useUpdateSettings();
  const { notify } = useToast();
  const [draft, setDraft] = useState(settings);
  useEffect(() => setDraft(settings), [settings]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);
  const setN = (k: keyof NotificationPreferences) => (v: boolean) => setDraft((d) => ({ ...d, notifications: { ...d.notifications, [k]: v } }));
  const save = () => update.mutate(draft, { onSuccess: () => notify('Settings saved', undefined, 'success') });

  return (
    <div>
      {section === 'general' ? (
        <div className="space-y-4">
          <Field label="Default landing page">
            <Select
              label="Default landing page"
              value={draft.defaultLandingPage}
              onChange={(v) => setDraft((d) => ({ ...d, defaultLandingPage: v }))}
              options={[
                { value: 'dashboard', label: 'Overview' },
                { value: 'results', label: 'My Results' },
                { value: 'reports', label: 'Reports' },
              ]}
            />
          </Field>
          <Field label="Date format">
            <Select
              label="Date format"
              value={draft.dateFormat}
              onChange={(v) => setDraft((d) => ({ ...d, dateFormat: v }))}
              options={[
                { value: 'mdy', label: 'Month Day, Year' },
                { value: 'dmy', label: 'Day Month Year' },
                { value: 'iso', label: 'YYYY-MM-DD' },
              ]}
            />
          </Field>
        </div>
      ) : (
        <div className="divide-y divide-line">
          <Toggle checked={draft.notifications.assessmentCompleted} onChange={setN('assessmentCompleted')} label="Health check finished" description="When a check is done." />
          <Toggle checked={draft.notifications.criticalFindings} onChange={setN('criticalFindings')} label="Critical problems" description="When something urgent is found." />
          <Toggle checked={draft.notifications.weeklyDigest} onChange={setN('weeklyDigest')} label="Weekly summary email" description="A short email each week." />
          <Toggle checked={draft.notifications.productUpdates} onChange={setN('productUpdates')} label="Product updates" description="News about new features." />
        </div>
      )}
      <div className="mt-4 space-y-3">
        <InlineError error={update.error} />
        <Button variant="primary" icon={<Save className="h-4 w-4" />} disabled={!dirty || update.isPending} onClick={save}>
          {update.isPending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get('tab'))?.id ?? 'preferences') as Tab;
  const { pref, setPref, reduceMotion, setReduceMotion } = useTheme();
  const me = useMe();
  const { isAdmin } = useRole();
  const authRequired = useAuthStatus().data?.authRequired ?? true;
  const settings = useSettings();
  const conn = useConnection();
  const health = useApiHealth();
  const navigate = useNavigate();

  const settingsBody = (section: 'general' | 'notifications') =>
    settings.isLoading ? <LoadingState rows={3} /> : settings.error ? <ErrorState error={settings.error} onRetry={() => settings.refetch()} /> : settings.data ? <SettingsForm settings={settings.data} section={section} /> : null;

  return (
    <div>
      <PageHeader title="Settings" description="Your preferences and profile." />

      <div className="card mb-6 px-5 pt-2">
        <Tabs<Tab> layoutId="settings-tabs" tabs={TABS} value={tab} onChange={(t) => setParams({ tab: t }, { replace: true })} />
      </div>

      {tab === 'preferences' && (
        <div className="grid gap-6 lg:grid-cols-[1.4fr,1fr]">
          <SectionCard title="Appearance" description="Stored on this device.">
            <div className="grid gap-3 sm:grid-cols-3">
              <ThemeCard id="light" label="Light" icon={<Sun className="h-4 w-4" />} active={pref === 'light'} onClick={() => setPref('light')} />
              <ThemeCard id="dark" label="Dark" icon={<Moon className="h-4 w-4" />} active={pref === 'dark'} onClick={() => setPref('dark')} />
              <ThemeCard id="system" label="System" icon={<Monitor className="h-4 w-4" />} active={pref === 'system'} onClick={() => setPref('system')} />
            </div>
            <div className="mt-4 border-t border-line">
              <Toggle checked={reduceMotion} onChange={setReduceMotion} label="Reduce motion" description="Turn off animations." />
            </div>
          </SectionCard>
          <SectionCard title="General" description="Saved to your account.">
            {settingsBody('general')}
          </SectionCard>
        </div>
      )}

      {tab === 'profile' && (
        <div className="space-y-6">
          <SectionCard title="Profile information">
            {me.isLoading ? <LoadingState rows={3} /> : me.error ? <ErrorState error={me.error} onRetry={() => me.refetch()} /> : me.data && <ProfileForm me={me.data} />}
          </SectionCard>
          {authRequired && <ChangePasswordCard />}
        </div>
      )}

      {tab === 'team' &&
        (isAdmin ? (
          <SectionCard title="Team & access">
            <p className="text-sm text-ink-muted">People, roles, org access and access requests are managed in the Admin Panel.</p>
            <Button variant="primary" className="mt-3" icon={<ShieldCheck className="h-4 w-4" />} onClick={() => navigate('/admin')}>Open the Admin Panel</Button>
          </SectionCard>
        ) : !authRequired ? (
          <SectionCard title="Team & access">
            <p className="text-sm text-ink-muted">Sign-in is turned off, so there’s no team to manage.</p>
          </SectionCard>
        ) : (
          <RequestAccessCard />
        ))}

      {tab === 'notifications' && (
        <SectionCard title="Notification preferences" description="Choose which events notify you.">
          {settingsBody('notifications')}
        </SectionCard>
      )}

      {tab === 'branding' &&
        (settings.isLoading ? <LoadingState rows={4} /> : settings.error ? <ErrorState error={settings.error} onRetry={() => settings.refetch()} /> : settings.data ? <ConsultingSettings settings={settings.data} /> : null)}

      {tab === 'security' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <SectionCard title="Platform">
            <ul className="space-y-3 text-sm">
              {[
                ['API endpoint', API_BASE_URL],
                ['API status', health.data ? `Online (v${health.data.version})` : health.isLoading ? 'Checking…' : 'Unavailable'],
                ['Frontend version', __APP_VERSION__],
                ['Salesforce token storage', 'Server-side (never in the browser)'],
              ].map(([k, v]) => (
                <li key={k} className="flex justify-between gap-4 border-b border-line pb-3 last:border-0 last:pb-0">
                  <span className="text-ink-muted">{k}</span>
                  <span className="break-all text-right font-medium">{v}</span>
                </li>
              ))}
            </ul>
          </SectionCard>
          <SectionCard title="Data handling">
            <ul className="space-y-3 text-sm">
              {[
                { title: 'No passwords', text: 'We never ask for your Salesforce password.' },
                { title: 'Keys kept safe', text: 'Access keys stay on our server, not in your browser.' },
                { title: 'Read-only', text: 'We only read your data. We never change it.' },
                { title: 'You’re in control', text: 'Disconnecting removes our access straight away.' },
              ].map((t) => (
                <li key={t.title} className="flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 shrink-0 text-good" />
                  {t.title}
                  <InfoTip label={`About: ${t.title}`}>{t.text}</InfoTip>
                </li>
              ))}
            </ul>
          </SectionCard>
        </div>
      )}

      {tab === 'organizations' && (
        <SectionCard title="Connected organizations" description="Your linked Salesforce.">
          {conn.isLoading ? (
            <LoadingState rows={2} />
          ) : conn.error ? (
            <ErrorState error={conn.error} onRetry={() => conn.refetch()} />
          ) : conn.data && conn.data.status !== 'disconnected' ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line p-4">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#00a1e0]/15 text-[#00a1e0]">
                  <Cloud className="h-5 w-5" />
                </span>
                <div>
                  <p className="text-sm font-medium">{conn.data.organizationName}</p>
                  <p className="text-xs text-ink-subtle">
                    {conn.data.orgId} · {conn.data.instanceUrl}
                    {conn.data.connectedAt && ` · connected ${fmtDateTime(conn.data.connectedAt)}`}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <ConnectionStatusBadge status={conn.data.status} />
                <Button size="sm" onClick={() => navigate('/connection')}>
                  Manage
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-ink-subtle">
                <Building2 className="h-6 w-6" />
              </span>
              <p className="text-sm font-semibold">No organizations connected</p>
              <Button variant="primary" onClick={() => navigate('/connection')}>
                Connect Salesforce
              </Button>
            </div>
          )}
        </SectionCard>
      )}
    </div>
  );
}
