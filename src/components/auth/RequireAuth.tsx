import { motion } from 'framer-motion';
import { RotateCw, ServerOff } from 'lucide-react';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { API_BASE_URL, errorMessage, isApiError } from '@/api/client';
import { useAuthStatus, useMe } from '@/api/queries';
import { BrandMark } from '../ui/Brand';
import { Button, LinkButton } from '../ui/Button';
import { ChooseOwnPassword } from './ChooseOwnPassword';

function FullScreen({ children }: { children: ReactNode }) {
  return <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-bg px-4 text-center">{children}</div>;
}

/**
 * Gate for authenticated routes. The backend is the real enforcement point;
 * this only decides whether to render the app, send the user to /login, or
 * explain that the service can't be reached.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuthStatus();
  const location = useLocation();
  if (status.isLoading) return <Checking />;
  // Can't tell (API down)? Let AuthGate explain; it shows the "can't reach the service" screen.
  if (status.data && !status.data.authRequired) return <>{children}</>;
  if (status.data?.needsSetup) return <Navigate to={`/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`} replace />;
  return <AuthGate>{children}</AuthGate>;
}

function Checking() {
  return (
    <FullScreen>
      <motion.div animate={{ opacity: [0.5, 1, 0.5] }} transition={{ duration: 1.6, repeat: Infinity }}>
        <BrandMark />
      </motion.div>
      <p className="text-sm text-ink-subtle">Checking your session…</p>
    </FullScreen>
  );
}

function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();

  if (me.data) return me.data.mustChangePassword ? <ChooseOwnPassword me={me.data} /> : <>{children}</>;

  if (me.isLoading) return <Checking />;

  if (isApiError(me.error) && (me.error.status === 401 || me.error.status === 403)) {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }

  return (
    <FullScreen>
      <BrandMark />
      <div className="card max-w-md p-8">
        <ServerOff className="mx-auto h-10 w-10 text-warn" />
        <h1 className="mt-3 text-lg font-semibold">We can’t reach the Aquarient service</h1>
        <p className="mt-1 text-sm text-ink-muted">{errorMessage(me.error)}</p>
        <p className="mt-2 text-xs text-ink-subtle">
          API endpoint: <code className="rounded bg-muted px-1">{API_BASE_URL}</code>
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <LinkButton to="/">Home</LinkButton>
          <Button variant="primary" icon={<RotateCw className="h-4 w-4" />} onClick={() => me.refetch()} disabled={me.isFetching}>
            {me.isFetching ? 'Retrying…' : 'Try again'}
          </Button>
        </div>
      </div>
    </FullScreen>
  );
}
