import { AnimatePresence, motion } from 'framer-motion';
import { ArrowLeft, ArrowRight, Building2, Check, Eye, EyeOff, KeyRound, Lock, Mail, MailCheck, ShieldCheck } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { errorMessage, isApiError } from '@/api/client';
import { userApi } from '@/api/endpoints';
import { useForgotPassword, useLogin, useMe, useSsoStart } from '@/api/queries';
import { ThemeToggle } from '@/components/layout/Header';
import { AUTH_REQUIRED } from '@/config/app';
import { BrandMark, LogoGlyph } from '@/components/ui/Brand';
import { Button } from '@/components/ui/Button';
import { CategoryIcon } from '@/components/ui/CategoryIcon';
import { Modal } from '@/components/ui/Overlay';
import { CATEGORIES, CATEGORY_COLORS, DIAGNOSTIC_AREAS } from '@/config/categories';
import { cx } from '@/lib/format';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const SSO_CALLBACK_PATH = '/login';

const LANDING: Record<string, string> = { dashboard: '/dashboard', results: '/results', reports: '/reports' };

/** Only allow same-origin relative paths as post-login redirects. */
function safeNext(next: string | null) {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/login')) return null;
  return next;
}

function loginErrorText(e: unknown) {
  if (!isApiError(e)) return errorMessage(e);
  if (e.status === 401) return 'Incorrect email or password.';
  if (e.status === 423) return 'This account is locked. Contact your administrator.';
  if (e.status === 429) return 'Too many sign-in attempts. Please wait a few minutes and try again.';
  return e.message;
}

function BrandPanel() {
  return (
    <div className="relative hidden overflow-hidden bg-brand text-white lg:flex lg:flex-col">
      <div className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 animate-floaty rounded-full bg-white/10 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-32 -right-24 h-[28rem] w-[28rem] animate-floaty rounded-full bg-accent/30 blur-3xl" />
      <div
        className="pointer-events-none absolute inset-0 opacity-20"
        style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.6) 1px, transparent 0)', backgroundSize: '22px 22px' }}
      />

      <div className="relative flex flex-1 flex-col justify-between p-12">
        <Link to="/" className="flex items-center gap-2.5" aria-label="Aquarient home">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white text-brand">
            <LogoGlyph className="h-6 w-6" />
          </span>
          <span className="leading-tight">
            <span className="block text-sm font-semibold">Aquarient</span>
            <span className="block text-[11px] text-white/70">CRM Health Platform</span>
          </span>
        </Link>

        <div>
          {/* Orbiting categories */}
          <div className="relative mb-10 h-56 w-56" aria-hidden="true">
            <div className="absolute inset-0 rounded-full border border-white/20" />
            <div className="absolute inset-8 rounded-full border border-dashed border-white/20" />
            <motion.div className="absolute inset-0" animate={{ rotate: 360 }} transition={{ duration: 40, repeat: Infinity, ease: 'linear' }}>
              {CATEGORIES.map((c, i) => {
                const a = (i / CATEGORIES.length) * Math.PI * 2;
                return (
                  <motion.span
                    key={c.id}
                    className="absolute flex h-10 w-10 items-center justify-center rounded-xl bg-white shadow-lg"
                    style={{ left: 112 + Math.cos(a) * 112 - 20, top: 112 + Math.sin(a) * 112 - 20, color: CATEGORY_COLORS[c.id] }}
                    animate={{ rotate: -360 }}
                    transition={{ duration: 40, repeat: Infinity, ease: 'linear' }}
                  >
                    <CategoryIcon id={c.id} className="h-5 w-5" />
                  </motion.span>
                );
              })}
            </motion.div>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="absolute h-16 w-16 animate-pulse-ring rounded-2xl border-2 border-white/60" />
              <span className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-white/15 backdrop-blur">
                <LogoGlyph className="h-9 w-9" />
              </span>
            </div>
          </div>

          <h2 className="max-w-md text-3xl font-semibold leading-tight tracking-tight">A simple health check for your Salesforce.</h2>
          <p className="mt-3 max-w-md text-white/80">
            {CATEGORIES.length} topics and {DIAGNOSTIC_AREAS.length} areas, checked for you.
          </p>
          <ul className="mt-6 space-y-2.5 text-sm text-white/90">
            {['We only read your data', 'Problems shown most urgent first', 'Easy reports to share'].map((t) => (
              <li key={t} className="flex items-center gap-2.5">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/20">
                  <Check className="h-3 w-3" />
                </span>
                {t}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-white/60">© {new Date().getFullYear()} Aquarient Technologies LLC</p>
      </div>
    </div>
  );
}

function ForgotPasswordModal({ open, onClose, initialEmail }: { open: boolean; onClose: () => void; initialEmail: string }) {
  const [email, setEmail] = useState(initialEmail);
  const [touched, setTouched] = useState(false);
  const forgot = useForgotPassword();
  useEffect(() => {
    if (open) {
      setEmail(initialEmail);
      setTouched(false);
      forgot.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const invalid = !EMAIL_RE.test(email.trim());

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!invalid) forgot.mutate({ email: email.trim() });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reset your password"
      description={forgot.isSuccess ? undefined : 'Enter your work email and we’ll send you a reset link.'}
      footer={
        forgot.isSuccess ? (
          <Button variant="primary" onClick={onClose}>
            Back to sign in
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" type="submit" form="forgot-form" disabled={forgot.isPending}>
              {forgot.isPending ? 'Sending…' : 'Send reset link'}
            </Button>
          </>
        )
      }
    >
      {forgot.isSuccess ? (
        <div className="flex flex-col items-center py-4 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-good-soft text-good">
            <MailCheck className="h-6 w-6" />
          </span>
          <p className="mt-3 text-sm font-semibold">Check your inbox</p>
          <p className="mt-1 max-w-sm text-sm text-ink-muted">If an account exists for {email.trim()}, you’ll receive an email with instructions to reset your password.</p>
        </div>
      ) : (
        <form id="forgot-form" onSubmit={submit} noValidate className="space-y-3">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium">Work email</span>
            <input type="email" autoComplete="email" className={cx('input h-10', touched && invalid && 'border-bad')} value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
            {touched && invalid && <span className="mt-1 block text-xs text-bad">Enter a valid email address</span>}
          </label>
          {forgot.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(forgot.error)}</p>}
        </form>
      )}
    </Modal>
  );
}

export default function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const me = useMe();
  const login = useLogin();
  const sso = useSsoStart();
  const next = safeNext(params.get('next'));

  const [mode, setMode] = useState<'password' | 'sso'>('password');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(true);
  const [showPw, setShowPw] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = 'Sign in — Aquarient CRM Health';
    emailRef.current?.focus();
    return () => {
      document.title = 'Aquarient CRM Health';
    };
  }, []);

  const emailError = !email.trim() ? 'Email is required' : !EMAIL_RE.test(email.trim()) ? 'Enter a valid email address' : null;
  const passwordError = mode === 'password' && !password ? 'Password is required' : null;
  const ssoError = params.get('error_description') ?? (params.get('error') ? 'Single sign-on failed. Please try again.' : null);

  // Already signed in → go straight to the app.
  // (Skipped right after a password login, which navigates itself to the user's preferred landing page.)
  if (AUTH_REQUIRED && me.data && !login.isPending && !login.isSuccess) return <Navigate to={next ?? '/dashboard'} replace />;

  const goToApp = async () => {
    if (next) return navigate(next, { replace: true });
    try {
      const s = await userApi.settings();
      navigate(LANDING[s.defaultLandingPage] ?? '/dashboard', { replace: true });
    } catch {
      navigate('/dashboard', { replace: true });
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (emailError || passwordError) return;
    if (mode === 'password') {
      login.mutateAsync({ email: email.trim(), password, rememberMe: remember }).then(goToApp, () => setPassword(''));
    } else {
      const redirectUri = `${window.location.origin}${SSO_CALLBACK_PATH}${next ? `?next=${encodeURIComponent(next)}` : ''}`;
      sso.mutateAsync({ email: email.trim(), redirectUri }).then(({ authorizationUrl }) => window.location.assign(authorizationUrl), () => undefined);
    }
  };

  const error = mode === 'password' ? (login.error ? loginErrorText(login.error) : null) : sso.error ? errorMessage(sso.error) : null;
  const pending = login.isPending || sso.isPending;

  return (
    <div className="grid min-h-screen bg-bg lg:grid-cols-[1fr,1.05fr]">
      <BrandPanel />

      <div className="flex flex-col">
        <div className="flex items-center justify-between px-6 py-5 sm:px-10">
          <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
            <ArrowLeft className="h-4 w-4" /> Home
          </Link>
          <ThemeToggle />
        </div>

        <main className="flex flex-1 items-center justify-center px-6 pb-16 sm:px-10">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }} className="w-full max-w-[400px]">
            <Link to="/" className="mb-8 inline-block lg:hidden" aria-label="Aquarient — go to the home page">
              <BrandMark />
            </Link>
            <h1 className="text-2xl font-semibold tracking-tight">Sign in to your workspace</h1>
            <p className="mt-1.5 text-sm text-ink-muted">
              {next ? 'Please sign in to continue.' : 'Welcome back. Use your work email.'}
            </p>

            {/* Mode switch */}
            <div className="mt-6 grid grid-cols-2 rounded-lg border border-line bg-muted p-1" role="tablist" aria-label="Sign-in method">
              {(
                [
                  ['password', 'Email & password', KeyRound],
                  ['sso', 'Single sign-on', Building2],
                ] as const
              ).map(([id, label, Icon]) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={mode === id}
                  onClick={() => {
                    setMode(id);
                    setSubmitted(false);
                  }}
                  className={cx('relative flex items-center justify-center gap-1.5 rounded-md py-2 text-sm font-medium transition', mode === id ? 'text-ink' : 'text-ink-muted hover:text-ink')}
                >
                  {mode === id && <motion.span layoutId="login-mode" className="absolute inset-0 rounded-md bg-surface shadow-card" transition={{ type: 'spring', stiffness: 500, damping: 36 }} />}
                  <Icon className="relative h-4 w-4" />
                  <span className="relative">{label}</span>
                </button>
              ))}
            </div>

            <form onSubmit={submit} noValidate className="mt-6 space-y-4">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium">Work email</span>
                <span className="relative block">
                  <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
                  <input
                    ref={emailRef}
                    type="email"
                    name="email"
                    autoComplete="username"
                    inputMode="email"
                    placeholder="name@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    aria-invalid={submitted && !!emailError}
                    aria-describedby={submitted && emailError ? 'email-error' : undefined}
                    className={cx('input h-11 pl-9', submitted && emailError && 'border-bad focus:border-bad focus:ring-bad/20')}
                  />
                </span>
                {submitted && emailError && (
                  <span id="email-error" className="mt-1 block text-xs text-bad">
                    {emailError}
                  </span>
                )}
              </label>

              <AnimatePresence initial={false} mode="wait">
                {mode === 'password' ? (
                  <motion.div key="pw" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="space-y-4 overflow-hidden">
                    <label className="block">
                      <span className="mb-1.5 flex items-center justify-between text-sm font-medium">
                        Password
                        <button type="button" onClick={() => setForgotOpen(true)} className="text-xs font-medium text-brand hover:underline">
                          Forgot password?
                        </button>
                      </span>
                      <span className="relative block">
                        <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-subtle" />
                        <input
                          type={showPw ? 'text' : 'password'}
                          name="password"
                          autoComplete="current-password"
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          onKeyUp={(e) => setCapsLock(e.getModifierState('CapsLock'))}
                          aria-invalid={submitted && !!passwordError}
                          className={cx('input h-11 pl-9 pr-10', submitted && passwordError && 'border-bad focus:border-bad focus:ring-bad/20')}
                        />
                        <button
                          type="button"
                          onClick={() => setShowPw((s) => !s)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-ink-subtle hover:text-ink"
                          aria-label={showPw ? 'Hide password' : 'Show password'}
                        >
                          {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </span>
                      {submitted && passwordError && <span className="mt-1 block text-xs text-bad">{passwordError}</span>}
                      {capsLock && <span className="mt-1 block text-xs text-warn">Caps Lock is on</span>}
                    </label>
                    <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-muted">
                      <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--brand))]" />
                      Keep me signed in on this device
                    </label>
                  </motion.div>
                ) : (
                  <motion.p key="sso" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden text-sm text-ink-muted">
                    We’ll send you to your company’s sign-in page.
                  </motion.p>
                )}
              </AnimatePresence>

              <AnimatePresence>
                {(error || ssoError) && (
                  <motion.p
                    role="alert"
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0, x: [0, -6, 6, -3, 3, 0] }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.35 }}
                    className="rounded-lg border border-bad/25 bg-bad-soft px-3 py-2.5 text-sm text-bad"
                  >
                    {error ?? ssoError}
                  </motion.p>
                )}
              </AnimatePresence>

              <Button type="submit" variant="primary" className="h-11 w-full text-[15px]" disabled={pending} iconRight={!pending ? <ArrowRight className="h-4 w-4" /> : undefined}>
                {pending ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                    {mode === 'password' ? 'Signing in…' : 'Redirecting…'}
                  </>
                ) : mode === 'password' ? (
                  'Sign in'
                ) : (
                  'Continue with SSO'
                )}
              </Button>
            </form>

            <div className="mt-8 rounded-xl border border-line bg-surface p-4">
              <p className="flex items-start gap-2.5 text-xs leading-relaxed text-ink-muted">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-good" />
                Never enter your Salesforce password here. You connect Salesforce separately.
              </p>
            </div>

            <p className="mt-6 text-center text-sm text-ink-muted">
              No access? Ask your Aquarient consultant.
            </p>
          </motion.div>
        </main>
      </div>

      <ForgotPasswordModal open={forgotOpen} onClose={() => setForgotOpen(false)} initialEmail={email} />
    </div>
  );
}
