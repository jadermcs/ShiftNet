import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';
import {
  contributionState,
  isSenseProposal,
  type Contribution,
  type ReferenceInput,
  type UsageProposal,
} from '../lib/contributions';
import { ChecksList } from './ChecksList';
import { ValidationBadge } from './ValidationBadge';

const when = (iso: string) => new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });

const refLine = (r: ReferenceInput, locator?: string) =>
  [r.author, r.title, [r.publisher, r.published_label ?? r.published_year].filter(Boolean).join(', '), locator, r.identifier]
    .filter(Boolean)
    .join('. ');

/** A proposed quotation and its reference. */
export function UsagePreview({ u }: { u: Omit<UsageProposal, 'sense_id'> }) {
  return (
    <div className="stack-4">
      <blockquote className="attestation-quote">
        <span className="mono small muted">{u.date_label || u.year} </span>
        {u.quote}
      </blockquote>
      <div className="attestation-ref">
        <span className="source-type">{u.source.kind}</span>
        <cite>{refLine(u.source, u.locator)}</cite>
        {u.source.url && (
          <a href={u.source.url} target="_blank" rel="noopener noreferrer nofollow" className="inline-link attestation-url">
            link
            <ExternalLink size={11} aria-hidden="true" />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        )}
        {u.source.accessed_on && <span className="small">accessed {u.source.accessed_on}</span>}
      </div>
    </div>
  );
}

/** A contribution with its state, content, checks and moderator note. children: actions. */
export function ContributionCard({
  c,
  showChecks = true,
  children,
}: {
  c: Contribution;
  showChecks?: boolean;
  children?: ReactNode;
}) {
  const state = contributionState(c);
  return (
    <article className="card contribution" aria-label={`${c.kind === 'sense' ? 'Proposed sense' : 'Proposed usage'} of ${c.lemma}`}>
      <header className="contribution-head">
        <span className="chip">{c.kind === 'sense' ? 'New sense' : 'Usage'}</span>
        <Link to={`/word/${encodeURIComponent(c.lemma)}`} className="contribution-lemma">
          {c.lemma}
        </Link>
        {c.sense_id && (
          <Link to={`/sense/${c.sense_id}`} className="mono small inline-link">
            {c.sense_id}
          </Link>
        )}
        <ValidationBadge state={state} />
        <span className="small muted push-right">
          {c.decided_at && c.status !== 'pending' ? `decided ${when(c.decided_at)}` : `sent ${when(c.created_at)}`}
        </span>
      </header>

      {isSenseProposal(c) ? (
        <div className="stack-8">
          <div className="small fg2">
            <em>{c.payload.pos}</em> · <span className="mono">{c.payload.date_label}</span> · <span className="chip chip-sm">{c.payload.shift}</span>
            {c.payload.parents.length > 0 && <> · from {c.payload.parents.map((p) => <Link key={p} to={`/sense/${p}`} className="mono inline-link contribution-parent">{p}</Link>)}</>}
          </div>
          <div className="gloss">{c.payload.gloss}</div>
          {c.payload.examples.length > 0 && (
            <div className="examples">
              {c.payload.examples.map((e) => (
                <em key={e}>“{e}”</em>
              ))}
            </div>
          )}
          <div className="small muted">Date source: {c.payload.date_source} ({c.payload.source_type})</div>
          {c.payload.usage && <UsagePreview u={c.payload.usage} />}
        </div>
      ) : (
        <UsagePreview u={c.payload as UsageProposal} />
      )}

      {showChecks && (
        <details className="contribution-checks" open={c.status === 'pending' || undefined}>
          <summary className="small muted">Automatic checks</summary>
          <ChecksList checks={c.checks} />
        </details>
      )}
      {c.review_note && (
        <p className="contribution-note small">
          <span className="label">Moderator note</span> {c.review_note}
        </p>
      )}
      {children}
    </article>
  );
}
