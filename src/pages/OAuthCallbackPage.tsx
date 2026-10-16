import { CircleDashed, XCircle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { errorMessage } from '@/api/client';
import { useCompleteOAuth } from '@/api/queries';
import { LinkButton } from '@/components/ui/Button';
import { useToast } from '@/context/ToastContext';
import { OAUTH_CALLBACK_PATH, OAUTH_STATE_KEY } from '@/config/oauth';

/** Salesforce redirects here after consent; the code is exchanged by the backend. */
export default function OAuthCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const complete = useCompleteOAuth();
  const ran = useRef(false);
  const [clientError, setClientError] = useState<string | null>(null);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const sfError = params.get('error_description') ?? params.get('error');
    const code = params.get('code');
    const state = params.get('state');
    if (sfError) return setClientError(`Salesforce returned an error: ${sfError}`);
    if (!code || !state) return setClientError('The authorization response is missing required parameters.');

    let expected: string | null = null;
    try {
      expected = sessionStorage.getItem(OAUTH_STATE_KEY);
      sessionStorage.removeItem(OAUTH_STATE_KEY);
    } catch {
      /* storage unavailable — backend validates state */
    }
    if (expected && expected !== state) return setClientError('Something went wrong. Please try connecting again.');

    // mutateAsync: the promise settles even if StrictMode remounts this component.
    complete
      .mutateAsync({ code, state, redirectUri: `${window.location.origin}${OAUTH_CALLBACK_PATH}` })
      .then((c) => {
        notify('Salesforce connected', c.organizationName ?? undefined, 'success');
        navigate('/connection', { replace: true });
      })
      .catch((e: unknown) => setClientError(errorMessage(e)));
  }, [params, complete, navigate, notify]);

  const failed = clientError;

  return (
    <div className="card mx-auto max-w-lg p-8 text-center">
      {failed ? (
        <>
          <XCircle className="mx-auto h-10 w-10 text-bad" />
          <h1 className="mt-3 text-lg font-semibold">Connection failed</h1>
          <p className="mt-1 text-sm text-ink-muted">{failed}</p>
          <LinkButton to="/connection" variant="primary" className="mt-5">
            Back to Connect Salesforce
          </LinkButton>
        </>
      ) : (
        <>
          <CircleDashed className="mx-auto h-10 w-10 animate-spin text-brand" />
          <h1 className="mt-3 text-lg font-semibold">Connecting to Salesforce…</h1>
          <p className="mt-1 text-sm text-ink-muted">This takes a moment.</p>
        </>
      )}
    </div>
  );
}
