import { AlertTriangle, CheckCircle2, Copy, Eye, EyeOff, KeyRound, Pencil, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { useClearSalesforceApp, useSalesforceApp, useSaveSalesforceApp } from '@/api/queries';
import { Button } from '@/components/ui/Button';
import { InfoTip } from '@/components/ui/HelpTip';
import { Modal } from '@/components/ui/Overlay';
import { SectionCard } from '@/components/ui/Page';
import { ErrorState, InlineError, LoadingState } from '@/components/ui/States';
import { useToast } from '@/context/ToastContext';
import { cx, fmtDateTime } from '@/lib/format';

// Same rules as the backend: letters, digits, and . _ - only.
const KEY_RE = /^[A-Za-z0-9._-]+$/;

const HOW_TO = [
  'In Salesforce Setup, open App Manager and click New Connected App (or New External Client App).',
  'Turn on OAuth settings and paste the Callback URL shown here.',
  'Add the scopes: api, refresh_token / offline_access.',
  'Turn on PKCE, save, then copy the Consumer Key and Consumer Secret.',
];

function CallbackUrl({ url }: { url: string }) {
  const { notify } = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      notify('Callback URL copied', undefined, 'success');
    } catch {
      notify('Couldn’t copy', 'Select the address and copy it by hand.', 'warning');
    }
  };
  return (
    <div>
      <span className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
        Callback URL
        <InfoTip>Paste this into your Salesforce app’s Callback URL box. It must match exactly.</InfoTip>
      </span>
      <div className="flex min-w-0 items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-lg border border-line bg-muted px-3 py-2 text-xs" title={url}>
          {url}
        </code>
        <Button size="sm" icon={<Copy className="h-3.5 w-3.5" />} onClick={copy} aria-label="Copy callback URL">
          Copy
        </Button>
      </div>
    </div>
  );
}

function KeysForm({ configured, onCancel, onSaved }: { configured: boolean; onCancel?: () => void; onSaved: () => void }) {
  const save = useSaveSalesforceApp();
  const [key, setKey] = useState('');
  const [secret, setSecret] = useState('');
  const [show, setShow] = useState(false);
  const [touched, setTouched] = useState(false);

  const k = key.trim();
  const s = secret.trim();
  const keyError = !k ? 'Paste the Consumer Key.' : k.length < 20 || !KEY_RE.test(k) ? 'This doesn’t look like a Consumer Key.' : null;
  const secretError = !s ? 'Paste the Consumer Secret.' : s.length < 8 || !KEY_RE.test(s) ? 'This doesn’t look like a Consumer Secret.' : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (keyError || secretError) return;
    save.mutate(
      { clientId: k, clientSecret: s },
      {
        onSuccess: () => {
          setSecret('');
          onSaved();
        },
      },
    );
  };

  const errClass = 'border-bad focus:border-bad focus:ring-bad/20';

  return (
    <form onSubmit={submit} className="space-y-4" autoComplete="off" noValidate>
      <label className="block">
        <span className="mb-1.5 block text-sm font-medium">Consumer Key</span>
        <input
          className={cx('input font-mono text-xs', touched && keyError && errClass)}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="3MVG9…"
          spellCheck={false}
          autoComplete="off"
          aria-invalid={!!(touched && keyError)}
        />
        {touched && keyError && <span className="mt-1 block text-xs text-bad">{keyError}</span>}
      </label>

      <label className="block">
        <span className="mb-1.5 block text-sm font-medium">Consumer Secret</span>
        <span className="relative block">
          <input
            type={show ? 'text' : 'password'}
            className={cx('input pr-10 font-mono text-xs', touched && secretError && errClass)}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            spellCheck={false}
            autoComplete="new-password"
            aria-invalid={!!(touched && secretError)}
          />
          <button
            type="button"
            onClick={() => setShow((v) => !v)}
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-ink-subtle hover:text-ink"
            aria-label={show ? 'Hide secret' : 'Show secret'}
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </span>
        {touched && secretError && <span className="mt-1 block text-xs text-bad">{secretError}</span>}
      </label>

      {configured && (
        <p className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-xs text-ink">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" />
          Using a different app will disconnect Salesforce. You’ll need to connect again.
        </p>
      )}

      <InlineError error={save.error} />

      <div className="flex flex-wrap justify-end gap-2">
        {onCancel && <Button onClick={onCancel}>Cancel</Button>}
        <Button variant="primary" type="submit" disabled={save.isPending} icon={<KeyRound className="h-4 w-4" />}>
          {save.isPending ? 'Saving…' : 'Save keys'}
        </Button>
      </div>
    </form>
  );
}

/**
 * One-time setup: the Salesforce admin pastes the Connected App keys here instead
 * of editing the server's .env file. The secret is stored encrypted on the server
 * and is never sent back to the browser.
 */
export function SalesforceAppSetup({
  editing,
  onEditingChange,
  onSaved,
}: {
  editing: boolean;
  onEditingChange: (v: boolean) => void;
  onSaved?: () => void;
}) {
  const app = useSalesforceApp();
  const clear = useClearSalesforceApp();
  const { notify } = useToast();
  const [confirmRemove, setConfirmRemove] = useState(false);

  const cfg = app.data;
  const showForm = !!cfg && (!cfg.configured || editing);

  return (
    <section>
      <SectionCard
        title="App keys"
        description={
          <>
            <span className="block">Your Salesforce app’s keys, stored encrypted on our server. A Salesforce admin sets this up once:</span>
            {HOW_TO.map((t, i) => (
              <span key={t} className="mt-1 block">
                {i + 1}. {t}
              </span>
            ))}
          </>
        }
        actions={
          cfg?.configured &&
          !editing && (
            <div className="flex gap-2">
              <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => onEditingChange(true)}>
                Change
              </Button>
              {cfg.source === 'ui' && (
                <Button size="sm" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setConfirmRemove(true)}>
                  Remove
                </Button>
              )}
            </div>
          )
        }
      >
        {app.isLoading ? (
          <LoadingState rows={2} label="Loading app setup…" />
        ) : app.error ? (
          <ErrorState error={app.error} onRetry={() => app.refetch()} />
        ) : (
          cfg && (
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="space-y-4">
                {cfg.configured && !editing ? (
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-good-soft text-good">
                      <CheckCircle2 className="h-[18px] w-[18px]" />
                    </span>
                    <div className="min-w-0 text-sm">
                      <p className="font-semibold">Keys saved</p>
                      <p className="mt-0.5 text-ink-muted">
                        Consumer Key <code className="font-mono text-xs">{cfg.clientIdPreview}</code>
                      </p>
                      <p className="mt-0.5 text-xs text-ink-subtle">
                        {cfg.source === 'env' ? 'From the server’s settings file' : 'Entered on this page'}
                        {cfg.updatedAt && ` · ${fmtDateTime(cfg.updatedAt)}`}
                      </p>
                    </div>
                  </div>
                ) : (
                  !cfg.configured && (
                    <p className="text-sm text-ink-muted">Add your Salesforce app’s keys once. Then anyone can click Connect.</p>
                  )
                )}
                <CallbackUrl url={cfg.callbackUrl} />
              </div>
              {showForm && (
                <KeysForm
                  configured={cfg.configured}
                  onCancel={cfg.configured ? () => onEditingChange(false) : undefined}
                  onSaved={() => {
                    onEditingChange(false);
                    notify('Keys saved', 'You can now connect Salesforce.', 'success');
                    onSaved?.();
                  }}
                />
              )}
            </div>
          )
        )}
      </SectionCard>

      <Modal
        open={confirmRemove}
        onClose={() => setConfirmRemove(false)}
        title="Remove app keys?"
        footer={
          <>
            <Button onClick={() => setConfirmRemove(false)}>Cancel</Button>
            <Button
              variant="danger"
              icon={<Trash2 className="h-4 w-4" />}
              disabled={clear.isPending}
              onClick={() =>
                clear.mutate(undefined, {
                  onSuccess: () => {
                    setConfirmRemove(false);
                    notify('App keys removed', undefined, 'success');
                  },
                })
              }
            >
              {clear.isPending ? 'Removing…' : 'Remove'}
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-ink-muted">
          <p>Salesforce will be disconnected. You’ll need to add keys again to reconnect.</p>
          <InlineError error={clear.error} />
        </div>
      </Modal>
    </section>
  );
}
