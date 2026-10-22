import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, Quote } from 'lucide-react';
import { fetchPendingForSense, useSession, type UsageProposal } from '../lib/contributions';
import { UsagePreview } from './ContributionCard';
import { ValidationBadge } from './ValidationBadge';

/**
 * Sense page: "Propose a usage", and the pending usages this viewer may see (their own; all for a
 * moderator), kept apart from the published attestations and labelled pending.
 */
export function SenseContribute({ senseId }: { senseId: string }) {
  const session = useSession();
  const pending = useQuery({
    queryKey: ['pending-usages', senseId, session?.user.id],
    queryFn: () => fetchPendingForSense(senseId),
    enabled: !!session,
  });
  const items = pending.data ?? [];

  return (
    <section className="card contribute-card" aria-labelledby="contrib-h">
      <div className="attestations-head">
        <h2 id="contrib-h" className="small-h">
          Know an earlier or better quotation?
        </h2>
        <Link to={`/contribute/usage?sense=${encodeURIComponent(senseId)}`} className="btn btn-sm">
          <Quote size={13} aria-hidden="true" />
          Propose a usage
        </Link>
      </div>
      {items.length > 0 && (
        <div className="stack-8 pending-block">
          <div className="row-gap wrap">
            <ValidationBadge state="pending" />
            <span className="small muted">
              Proposed, not part of the lexicon until a moderator accepts it. Only the contributor and moderators see these.
            </span>
          </div>
          <ol className="attestations">
            {items.map((c) => (
              <li key={c.id} className="pending-item">
                <UsagePreview u={c.payload as UsageProposal} />
              </li>
            ))}
          </ol>
          <Link to="/contribute" className="link-quiet small">
            Your contributions
          </Link>
        </div>
      )}
    </section>
  );
}

/** Word page: "Propose a sense". */
export function WordContribute({ lemma }: { lemma: string }) {
  return (
    <div className="card contribute-card contribute-inline">
      <span className="small muted">Missing a sense of “{lemma}”?</span>
      <Link to={`/contribute/sense?lemma=${encodeURIComponent(lemma)}`} className="btn btn-sm">
        <Plus size={13} aria-hidden="true" />
        Propose a sense
      </Link>
    </div>
  );
}
