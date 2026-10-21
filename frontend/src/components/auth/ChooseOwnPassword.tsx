import { KeyRound, LogOut } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { errorMessage } from '@/api/client';
import { useChangePassword, useLogout } from '@/api/queries';
import type { UserProfile } from '@/types';
import { BrandMark } from '../ui/Brand';
import { Button } from '../ui/Button';
import { Field } from '../ui/Form';

/** Shown instead of the app when someone signed in with a default/temporary password. */
export function ChooseOwnPassword({ me }: { me: UserProfile }) {
  const change = useChangePassword();
  const logout = useLogout();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const mismatch = !!confirm && confirm !== next;
  const ready = !!current && next.length >= 10 && next === confirm && !change.isPending;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (ready) change.mutate({ currentPassword: current, newPassword: next });
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-bg px-4 py-10">
      <BrandMark />
      <div className="card w-full max-w-md p-6 sm:p-8">
        <span className="grid h-11 w-11 place-items-center rounded-full bg-brand-soft text-brand">
          <KeyRound className="h-5 w-5" />
        </span>
        <h1 className="mt-4 text-xl font-semibold">Choose your own password</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Welcome, {me.name.split(' ')[0]}. You signed in with a temporary password, so please set a new one that only you know.
        </p>
        <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
          <Field label="Temporary password">
            <input type="password" autoComplete="current-password" className="input" value={current} onChange={(e) => setCurrent(e.target.value)} autoFocus />
          </Field>
          <Field label="New password" hint="At least 10 characters, and different from the temporary one.">
            <input type="password" autoComplete="new-password" className="input" value={next} onChange={(e) => setNext(e.target.value)} />
          </Field>
          <Field label="Confirm new password">
            <input type="password" autoComplete="new-password" className={mismatch ? 'input border-bad' : 'input'} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            {mismatch && <span className="mt-1 block text-xs text-bad">Passwords don’t match</span>}
          </Field>
          {change.error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{errorMessage(change.error)}</p>}
          <Button type="submit" variant="primary" className="w-full justify-center" disabled={!ready}>
            {change.isPending ? 'Saving…' : 'Save and continue'}
          </Button>
        </form>
        <button
          onClick={() => logout.mutate(undefined, { onSettled: () => window.location.assign('/login') })}
          className="mx-auto mt-4 flex items-center gap-1.5 text-xs text-ink-subtle hover:text-ink"
        >
          <LogOut className="h-3.5 w-3.5" /> Sign out
        </button>
      </div>
    </div>
  );
}
