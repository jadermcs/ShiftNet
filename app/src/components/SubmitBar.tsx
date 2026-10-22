import { Link } from 'react-router-dom';
import { CheckCircle2, Clock, ListChecks, Send } from 'lucide-react';
import type { Check, Contribution } from '../lib/contributions';
import { ChecksList, checksOutcome } from './ChecksList';
import { ValidationBadge } from './ValidationBadge';

/** Run checks / Submit buttons, with the latest check results or error. */
export function SubmitBar({
  busy,
  checks,
  error,
  onCheck,
}: {
  busy: boolean;
  checks: Check[] | null;
  error: string | null;
  onCheck: () => void;
}) {
  const outcome = checks && checksOutcome(checks);
  return (
    <div className="stack-10">
      {checks && (
        <div className={`check-summary check-summary-${outcome}`} role="status" aria-live="polite">
          <strong className="small">
            {outcome === 'error'
              ? 'Fix the fields below before submitting.'
              : outcome === 'review'
                ? 'This can be submitted; a moderator will review it before it is published.'
                : 'Every check passes: this will be published as soon as you submit it.'}
          </strong>
          <ChecksList checks={checks} />
        </div>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="row-gap wrap">
        <button type="button" className="btn" disabled={busy} onClick={onCheck}>
          <ListChecks size={14} aria-hidden="true" />
          Run checks
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          <Send size={14} aria-hidden="true" />
          {busy ? 'Working…' : 'Submit'}
        </button>
      </div>
    </div>
  );
}

/** What happened to a submission. */
export function SubmitResult({ c, onAnother }: { c: Contribution; onAnother: () => void }) {
  const published = c.status === 'accepted';
  return (
    <section className="card form-card" role="status" aria-live="polite">
      <div className="row-gap wrap">
        {published ? <CheckCircle2 size={18} className="check-pass-icon" aria-hidden="true" /> : <Clock size={18} className="check-review-icon" aria-hidden="true" />}
        <h2 className="form-title">{published ? 'Published' : 'Sent for review'}</h2>
        <ValidationBadge state={published ? (c.validation ?? 'automatic') : 'pending'} />
      </div>
      <p className="small fg2">
        {published
          ? 'Your contribution passed every automatic check and is now part of the lexicon, marked as auto-checked until a moderator confirms it.'
          : 'The automatic checks flagged something for a person to look at. It is not part of the lexicon until a moderator accepts it; you can follow it under My contributions.'}
      </p>
      <ChecksList checks={c.checks} />
      <div className="row-gap wrap">
        {published && c.sense_id && (
          <Link to={`/sense/${c.sense_id}`} className="btn btn-primary">
            View the sense
          </Link>
        )}
        <Link to="/contribute" className="btn">
          My contributions
        </Link>
        <button className="btn" onClick={onAnother}>
          Propose another
        </button>
      </div>
    </section>
  );
}
