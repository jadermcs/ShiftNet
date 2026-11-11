import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Undo2, X } from 'lucide-react';
import { fetchQueue, reviewContribution, type Contribution, type QueueFilter, type ReviewDecision } from '../lib/contributions';
import { ContributionCard } from '../components/ContributionCard';
import { Field } from '../components/Field';
import { useCrumbs } from '../components/Shell';
import { Empty, ErrorState, Loading } from '../components/States';

const TABS: { id: QueueFilter; label: string; empty: string }[] = [
  { id: 'pending', label: 'Needs review', empty: 'Nothing is waiting for review.' },
  { id: 'unconfirmed', label: 'Auto-accepted', empty: 'No auto-accepted contributions left to confirm.' },
  { id: 'decided', label: 'Reviewed', empty: 'No reviews yet.' },
];

export function ReviewQueue() {
  useCrumbs([{ label: 'Contribute', to: '/contribute' }, { label: 'Review queue' }]);
  return (
    <>
      <div className="card page-head">
        <span className="label">Moderation</span>
        <h1 className="h-page">Review queue</h1>
        <p className="muted">
          Contributions the automatic checks flagged wait here. Accepting one publishes it as <em>Reviewed</em>; rejecting
          one needs a note, kept with it. Auto-accepted contributions are already in the lexicon: confirm them, or withdraw
          them.
        </p>
      </div>
      <Queue />
    </>
  );
}

function Queue() {
  const [tab, setTab] = useState<QueueFilter>('pending');
  const items = useQuery({ queryKey: ['queue', tab], queryFn: () => fetchQueue(tab) });

  return (
    <>
      <div role="tablist" aria-label="Queue" className="segmented queue-tabs">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)!.label} className="stack-8">
        {items.isPending && <Loading rows={2} />}
        {items.isError && <ErrorState error={items.error} retry={() => items.refetch()} />}
        {items.data?.length === 0 && <Empty>{TABS.find((t) => t.id === tab)!.empty}</Empty>}
        {items.data?.map((c) => (
          <ContributionCard key={c.id} c={c}>
            {tab !== 'decided' && <ReviewActions c={c} />}
          </ContributionCard>
        ))}
      </div>
    </>
  );
}

function ReviewActions({ c }: { c: Contribution }) {
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const pending = c.status === 'pending';
  const review = useMutation({
    mutationFn: (d: ReviewDecision) => reviewContribution(c.id, d, note.trim()),
    // Accepting or withdrawing changes senses, attestations, charts and lists: refetch everything.
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <div className="review-actions">
      <Field label="Review note" hint="Required when rejecting">
        <textarea className="input textarea" rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {review.isError && (
        <p className="field-error" role="alert">
          {review.error.message}
        </p>
      )}
      <div className="row-gap wrap">
        <button className="btn btn-primary" disabled={review.isPending} onClick={() => review.mutate('accept')}>
          <Check size={14} aria-hidden="true" />
          {pending ? 'Accept and publish' : 'Confirm'}
        </button>
        <button className="btn" disabled={review.isPending || !note.trim()} onClick={() => review.mutate('reject')}>
          {pending ? <X size={14} aria-hidden="true" /> : <Undo2 size={14} aria-hidden="true" />}
          {pending ? 'Reject' : 'Withdraw from the lexicon'}
        </button>
      </div>
    </div>
  );
}
