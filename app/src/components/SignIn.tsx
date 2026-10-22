import { useState, type ReactNode, type SyntheticEvent } from 'react';
import { useLocation } from 'react-router-dom';
import type { Session } from '@supabase/supabase-js';
import { Github, LogIn, Mail } from 'lucide-react';
import { sendSignInEmail, signInWithGitHub, useSession, verifySignInCode } from '../lib/contributions';
import { Field } from './Field';
import { Loading } from './States';

/** GitHub sign-in, or email: a magic link, or the 6-digit code from the same email (for another device). */
export function SignIn({ intro }: { intro?: ReactNode }) {
  const loc = useLocation();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: SyntheticEvent, fn: () => Promise<void>) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card form-card" aria-labelledby="signin-h">
      <div className="stack-4">
        <h2 id="signin-h" className="form-title">
          Sign in to contribute
        </h2>
        <p className="muted small">
          {intro ??
            'Browsing needs no account. To propose usages or senses, sign in with GitHub or with your email address: we send a link and a code, no password.'}
        </p>
      </div>
      {!sentTo && (
        <div>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={(e) => run(e, () => signInWithGitHub(loc.pathname + loc.search))}
          >
            <Github size={14} aria-hidden="true" />
            Continue with GitHub
          </button>
        </div>
      )}
      {sentTo ? (
        <form className="stack-10" onSubmit={(e) => run(e, () => verifySignInCode(sentTo, code.trim()))}>
          <p className="small fg2" role="status">
            <Mail size={14} aria-hidden="true" className="icon-muted inline-icon" /> We sent an email to <strong>{sentTo}</strong>. Open
            the link in this browser, or type the 6-digit code here.
          </p>
          <div className="form-row">
            <Field label="Code" required error={error}>
              <input
                className="input input-code mono"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              />
            </Field>
          </div>
          <div className="row-gap wrap">
            <button className="btn btn-primary" disabled={busy || code.length !== 6}>
              <LogIn size={14} aria-hidden="true" />
              Sign in
            </button>
            <button type="button" className="link-btn underline small" onClick={() => setSentTo(null)}>
              Use another address
            </button>
          </div>
        </form>
      ) : (
        <form
          className="stack-10"
          onSubmit={(e) =>
            run(e, async () => {
              await sendSignInEmail(email.trim(), loc.pathname + loc.search);
              setSentTo(email.trim());
            })
          }
        >
          <div className="form-row">
            <Field label="Email address" required error={error}>
              <input className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
          </div>
          <div>
            <button className="btn btn-primary" disabled={busy || !email.trim()}>
              <Mail size={14} aria-hidden="true" />
              {busy ? 'Sending…' : 'Email me a sign-in link'}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

/** Renders children with the session, or the sign-in form. */
export function RequireSignIn({ intro, children }: { intro?: ReactNode; children: (s: Session) => ReactNode }) {
  const session = useSession();
  if (session === undefined) return <Loading label="Checking sign-in…" />;
  if (!session) return <SignIn intro={intro} />;
  return <>{children(session)}</>;
}
