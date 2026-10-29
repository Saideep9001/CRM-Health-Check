import { ArrowRight, CheckCircle2, ExternalLink, FileSpreadsheet, KeyRound, Play, Plus, ServerCog, ShieldCheck, Table2, Trash2, Upload } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAssessments, useCheckConnection, useConnection, useConnectionSnapshot, useHideOrg, useRemoveUploadedObject, useSalesforceApp, useStartOAuth, useRole, useUploadedObjects } from '@/api/queries';
import { OrgSnapshot } from '@/components/connection/OrgSnapshot';
import { ScoreRing } from '@/components/ui/Visuals';
import { SalesforceConnectionCard } from '@/components/connection/SalesforceConnectionCard';
import { DisconnectDialog } from '@/components/connection/DisconnectDialog';
import { UploadDataModal } from '@/components/connection/UploadDataModal';
import { Button, LinkButton } from '@/components/ui/Button';
import { Field } from '@/components/ui/Form';
import { InfoTip } from '@/components/ui/HelpTip';
import { OAUTH_CALLBACK_PATH, OAUTH_STATE_KEY } from '@/config/oauth';
import { Modal } from '@/components/ui/Overlay';
import { PageHeader, SectionCard } from '@/components/ui/Page';
import { ErrorState, InlineError, LoadingState } from '@/components/ui/States';
import { useToast } from '@/context/ToastContext';
import { cx, fmtAgo, fmtNumber, scoreBand } from '@/lib/format';
import type { SalesforceEnvironment } from '@/types';


const STEPS = [
  { icon: KeyRound, title: 'Sign in to Salesforce', text: 'Sign in on Salesforce’s own page. We never see your password.' },
  { icon: ShieldCheck, title: 'Allow read-only access', text: 'You allow us to read your data. We never change it.' },
  { icon: ServerCog, title: 'Kept safe', text: 'Access keys stay on our server, not in your browser.' },
  { icon: CheckCircle2, title: 'Run health checks', text: 'You get a score and a list of fixes.' },
];

const ENVIRONMENTS: { id: SalesforceEnvironment; label: string; host: string }[] = [
  { id: 'production', label: 'My live Salesforce (most common)', host: 'login.salesforce.com' },
  { id: 'sandbox', label: 'A test copy (sandbox)', host: 'test.salesforce.com' },
  { id: 'custom', label: 'My company’s own Salesforce address', host: 'e.g. acme.my.salesforce.com' },
];

const MY_DOMAIN_RE = /^[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*\.(my\.salesforce\.com|my\.salesforce-sites\.com|lightning\.force\.com)$/i;

export function ConnectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<SalesforceEnvironment>('production');
  const [domain, setDomain] = useState('');
  const [touched, setTouched] = useState(false);
  const start = useStartOAuth();
  const cleaned = domain.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
  const domainError = env === 'custom' && !MY_DOMAIN_RE.test(cleaned) ? 'Enter a valid My Domain, e.g. acme.my.salesforce.com' : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (domainError) return;
    start.mutate(
      { environment: env, myDomain: env === 'custom' ? cleaned : undefined, redirectUri: `${window.location.origin}${OAUTH_CALLBACK_PATH}` },
      {
        onSuccess: ({ authorizationUrl, state }) => {
          try {
            sessionStorage.setItem(OAUTH_STATE_KEY, state);
          } catch {
            // The backend still validates `state`; the client check is defence in depth.
          }
          window.location.assign(authorizationUrl);
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Connect Salesforce"
      description="You’ll sign in on Salesforce’s own page."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="connect-form" disabled={start.isPending} iconRight={<ExternalLink className="h-4 w-4" />}>
            {start.isPending ? 'Redirecting…' : 'Continue to Salesforce'}
          </Button>
        </>
      }
    >
      <form id="connect-form" onSubmit={submit} className="space-y-4">
        <fieldset>
          <legend className="mb-2 flex items-center gap-1.5 text-sm font-medium">
            Which Salesforce do you want to connect?
            <InfoTip>Not sure? Pick the first option.</InfoTip>
          </legend>
          <div className="grid gap-2">
            {ENVIRONMENTS.map((e) => (
              <label
                key={e.id}
                className={cx(
                  'flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition',
                  env === e.id ? 'border-brand bg-brand-soft' : 'border-line hover:bg-muted',
                )}
              >
                <input type="radio" name="env" value={e.id} checked={env === e.id} onChange={() => setEnv(e.id)} className="accent-[rgb(var(--brand))]" />
                <span className="flex-1">
                  <span className="block text-sm font-medium">{e.label}</span>
                  <span className="block text-xs text-ink-subtle">{e.host}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {env === 'custom' && (
          <Field label="My Domain" hint="e.g. acme.my.salesforce.com">
            <input
              className={cx('input', touched && domainError && 'border-bad focus:border-bad focus:ring-bad/20')}
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              onBlur={() => setTouched(true)}
              placeholder="acme.my.salesforce.com"
              autoComplete="off"
              aria-invalid={!!(touched && domainError)}
            />
            {touched && domainError && <span className="mt-1 block text-xs text-bad">{domainError}</span>}
          </Field>
        )}
        <InlineError error={start.error} />
        <p className="text-xs text-ink-subtle">
          Admin?{' '}
          <Link to="/connection/setup" className="font-medium text-brand hover:underline">
            Manage Salesforce app keys
          </Link>
        </p>
      </form>
    </Modal>
  );
}

/** This org's latest health checks, with a quick way to run another. */
function RecentChecks({ orgId, canRun }: { orgId: string; canRun: boolean }) {
  const all = useAssessments();
  const mine = (all.data ?? []).filter((a) => a.orgId === orgId && a.status === 'completed').slice(0, 3);
  const running = (all.data ?? []).find((a) => a.orgId === orgId && (a.status === 'running' || a.status === 'queued'));
  return (
    <SectionCard
      className="mt-6"
      title="Health checks for this org"
      actions={canRun && <LinkButton to="/assessment" size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />}>Run a health check</LinkButton>}
      bodyClassName="p-0"
    >
      {running && (
        <Link to="/history" className="flex items-center gap-3 border-b border-line bg-brand-soft/60 px-6 py-3 text-sm">
          <span className="relative flex h-2.5 w-2.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-60" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" /></span>
          <span className="flex-1"><span className="font-medium">{running.name}</span> is running now</span>
          <ArrowRight className="h-4 w-4 text-brand" />
        </Link>
      )}
      {all.isLoading ? (
        <div className="p-6"><LoadingState rows={2} /></div>
      ) : !mine.length ? (
        <p className="px-6 py-6 text-sm text-ink-muted">No health checks for this org yet. Run one to get a score and a list of fixes.</p>
      ) : (
        <ul className="divide-y divide-line">
          {mine.map((a) => (
            <li key={a.id}>
              <Link to={`/results?assessment=${encodeURIComponent(a.id)}`} className="flex items-center gap-4 px-6 py-3 hover:bg-muted/60">
                <ScoreRing score={a.overallScore} size={44} stroke={5} showBand={false} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{a.name}</p>
                  <p className="text-xs text-ink-subtle">{a.completedAt ? fmtAgo(a.completedAt) : ''}</p>
                </div>
                <span className="text-xs font-medium" style={{ color: scoreBand(a.overallScore).color }}>{scoreBand(a.overallScore).label}</span>
                <ArrowRight className="h-4 w-4 text-ink-subtle" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

/** The files in the active upload: one per object, each replaceable or removable. */
function UploadedFiles({ orgId, canEdit, onAdd }: { orgId: string; canEdit: boolean; onAdd: () => void }) {
  const files = useUploadedObjects(orgId, true);
  const remove = useRemoveUploadedObject();
  return (
    <SectionCard
      className="mt-6"
      title="Uploaded files"
      description="One file per object. Loading a file for an object again replaces it."
      actions={canEdit && <Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={onAdd}>Add a file</Button>}
      bodyClassName="p-0"
    >
      {files.isLoading ? (
        <div className="p-6"><LoadingState rows={2} /></div>
      ) : (
        <ul className="divide-y divide-line">
          {(files.data ?? []).map((o) => (
            <li key={o.name} className="flex items-center gap-4 px-6 py-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand"><FileSpreadsheet className="h-4 w-4" /></span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{o.plural} <span className="font-normal text-ink-subtle">· {fmtNumber(o.rows)} records</span></p>
                <p className="truncate text-xs text-ink-subtle">{o.filename}{o.loadedAt ? ` · loaded ${fmtAgo(o.loadedAt)}` : ''}</p>
              </div>
              <LinkButton to={`/data/${encodeURIComponent(o.name)}`} size="sm" icon={<Table2 className="h-3.5 w-3.5" />}>Open table</LinkButton>
              {canEdit && (
                <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} disabled={remove.isPending} onClick={() => remove.mutate({ orgId, name: o.name })}>
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <InlineError error={files.error ?? remove.error} />
    </SectionCard>
  );
}

export default function ConnectionPage() {
  const conn = useConnection();
  const check = useCheckConnection();
  const { canEdit, isAdmin } = useRole();
  const { notify } = useToast();
  const [connectOpen, setConnectOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const hide = useHideOrg();
  const app = useSalesforceApp();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  // Coming back from the setup page after saving keys: continue straight to Connect.
  useEffect(() => {
    if (params.get('connect') === '1') {
      setConnectOpen(true);
      setParams({}, { replace: true });
    }
  }, [params, setParams]);

  // Re-check quietly on open when the last check is over an hour old, so the status shown is current.
  const autoChecked = useRef(false);
  useEffect(() => {
    const c = conn.data;
    if (autoChecked.current || !c || c.status !== 'connected' || c.environment === 'upload') return;
    autoChecked.current = true;
    const last = c.lastCheckedAt ? new Date(c.lastCheckedAt).getTime() : 0;
    if (Date.now() - last > 60 * 60_000) check.mutate();
  }, [conn.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const isConnected = conn.data?.status === 'connected';
  const orgId = conn.data?.orgId ?? null;
  const isUpload = conn.data?.environment === 'upload';
  const snapshot = useConnectionSnapshot(orgId, isConnected).data ?? null;

  // Without app keys, Connect can't work yet: go to the setup page first.
  const onConnect = () => {
    if (app.data && !app.data.configured) navigate('/connection/setup');
    else setConnectOpen(true);
  };

  return (
    <div>
      <PageHeader
        title="Connect Salesforce"
        description="Link your Salesforce. We only read your data."
      />

      {conn.isLoading ? (
        <div className="card">
          <LoadingState rows={4} label="Loading connection…" />
        </div>
      ) : conn.error ? (
        <div className="card">
          <ErrorState error={conn.error} onRetry={() => conn.refetch()} />
        </div>
      ) : (
        conn.data && (
          <SalesforceConnectionCard
            connection={conn.data}
            onConnect={canEdit ? onConnect : undefined}
            onDisconnect={isAdmin ? () => setConfirmOpen(true) : undefined}
            onHide={
              conn.data.orgId
                ? () =>
                    hide.mutate(conn.data!.orgId!, {
                      onSuccess: () => notify('Removed from your list', 'Everyone else still has it. Add it back any time from Client Portfolio.', 'success'),
                      onError: (e) => notify('Couldn’t remove it', e.message, 'warning'),
                    })
                : undefined
            }
            checking={check.isPending}
            snapshot={snapshot}
            onCheck={() =>
              check.mutate(undefined, {
                onSuccess: (c) => notify(c.status === 'connected' ? 'Connection healthy' : 'Connection needs attention', c.errorMessage ?? undefined, c.status === 'connected' ? 'success' : 'warning'),
                onError: (e) => notify('Connection check failed', e.message, 'warning'),
              })
            }
          />
        )
      )}

      {isConnected && orgId && isUpload && <UploadedFiles orgId={orgId} canEdit={canEdit} onAdd={() => setUploadOpen(true)} />}
      {isConnected && orgId && !isUpload && <OrgSnapshot orgId={orgId} />}
      {isConnected && orgId && <RecentChecks orgId={orgId} canRun={canEdit} />}

      {canEdit && !isUpload && (
        <section className="mt-6 flex flex-col gap-4 rounded-2xl border border-dashed border-line bg-muted/30 p-5 sm:flex-row sm:items-center">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"><FileSpreadsheet className="h-5 w-5" /></span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">No Salesforce access? Upload a file instead</p>
            <p className="text-sm text-ink-muted">A CSV or Excel export of Accounts, Contacts, Leads, Opportunities or any other records — checked with the same rules.</p>
          </div>
          <Button icon={<Upload className="h-4 w-4" />} onClick={() => setUploadOpen(true)}>Upload CSV or Excel</Button>
        </section>
      )}

      {!isConnected && (
      <SectionCard className="mt-6" title="What happens when you connect" description="Takes about a minute">
        <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand-ink">
                <s.icon className="h-[18px] w-[18px]" />
              </span>
              <p className="flex items-center gap-1.5 self-center text-sm font-semibold">
                {i + 1}. {s.title}
                <InfoTip label={`About step ${i + 1}`}>{s.text}</InfoTip>
              </p>
            </li>
          ))}
        </ol>
      </SectionCard>
      )}

      <ConnectModal open={connectOpen} onClose={() => setConnectOpen(false)} />
      <UploadDataModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        addTo={isUpload && orgId ? { orgId, name: conn.data?.organizationName ?? 'this upload' } : null}
      />

      <DisconnectDialog open={confirmOpen} orgId={conn.data?.orgId ?? null} orgName={conn.data?.organizationName ?? 'this org'} onClose={() => setConfirmOpen(false)} />
    </div>
  );
}
