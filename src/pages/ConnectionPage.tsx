import { CheckCircle2, ExternalLink, KeyRound, ServerCog, ShieldCheck, Unplug } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useCheckConnection, useConnection, useDisconnect, useSalesforceApp, useStartOAuth } from '@/api/queries';
import { SalesforceConnectionCard } from '@/components/connection/SalesforceConnectionCard';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Form';
import { InfoTip } from '@/components/ui/HelpTip';
import { OAUTH_CALLBACK_PATH, OAUTH_STATE_KEY } from '@/config/oauth';
import { Modal } from '@/components/ui/Overlay';
import { PageHeader, SectionCard } from '@/components/ui/Page';
import { ErrorState, InlineError, LoadingState } from '@/components/ui/States';
import { useToast } from '@/context/ToastContext';
import { cx } from '@/lib/format';
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

export default function ConnectionPage() {
  const conn = useConnection();
  const check = useCheckConnection();
  const disconnect = useDisconnect();
  const { notify } = useToast();
  const [connectOpen, setConnectOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
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
            onConnect={onConnect}
            onDisconnect={() => setConfirmOpen(true)}
            checking={check.isPending}
            onCheck={() =>
              check.mutate(undefined, {
                onSuccess: (c) => notify(c.status === 'connected' ? 'Connection healthy' : 'Connection needs attention', c.errorMessage ?? undefined, c.status === 'connected' ? 'success' : 'warning'),
                onError: (e) => notify('Connection check failed', e.message, 'warning'),
              })
            }
          />
        )
      )}

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

      <ConnectModal open={connectOpen} onClose={() => setConnectOpen(false)} />

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Disconnect Salesforce?"
        description={conn.data?.organizationName ?? undefined}
        footer={
          <>
            <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
            <Button
              variant="danger"
              icon={<Unplug className="h-4 w-4" />}
              disabled={disconnect.isPending}
              onClick={() =>
                disconnect.mutate(undefined, {
                  onSuccess: () => {
                    setConfirmOpen(false);
                    notify('Salesforce disconnected', 'Stored tokens have been revoked.', 'success');
                  },
                })
              }
            >
              {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-ink-muted">
          <p>Your past results are kept. You’ll need to reconnect to run new checks.</p>
          <InlineError error={disconnect.error} />
        </div>
      </Modal>
    </div>
  );
}
