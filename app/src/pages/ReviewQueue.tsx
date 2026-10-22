import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Session } from '@supabase/supabase-js';
import { Check, Undo2, X } from 'lucide-react';
import { fetchQueue, reviewContribution, useIsModerator, type Contribution, type QueueFilter, type ReviewDecision } from '../lib/contributions';
import { ContributionCard } from '../components/ContributionCard';
import { Field } from '../components/Field';
import { useCrumbs } from '../components/Shell';
import { RequireSignIn } from '../components/SignIn';
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
          one needs a note, which the contributor sees. Auto-accepted contributions are already public: confirm them, or
          withdraw them from the lexicon.
        </p>
      </div>
      <RequireSignIn intro="Sign in with your moderator account.">{(s) => <Queue session={s} />}</RequireSignIn>
    </>
  );
}

function Queue({ session }: { session: Session }) {
  const [tab, setTab] = useState<QueueFilter>('pending');
  const mod = useIsModerator(session);
  const items = useQuery({ queryKey: ['queue', tab], queryFn: () => fetchQueue(tab), enabled: mod.data === true });

  if (mod.isPending) return <Loading label="Checking permissions…" />;
  if (mod.isError) return <ErrorState error={mod.error} retry={() => mod.refetch()} />;
  if (!mod.data) return <Empty>Only moderators can review contributions. Your own contributions are under Contribute.</Empty>;

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
            {tab !== 'decided' && <ReviewActions c={c} own={c.contributor_id === session.user.id} />}
            {tab === 'decided' && (
              <p className="small muted">Contributor <span className="mono">{c.contributor_id.slice(0, 8)}</span></p>
            )}
          </ContributionCard>
        ))}
      </div>
    </>
  );
}

function ReviewActions({ c, own }: { c: Contribution; own: boolean }) {
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const pending = c.status === 'pending';
  const review = useMutation({
    mutationFn: (d: ReviewDecision) => reviewContribution(c.id, d, note.trim()),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['queue'] });
      qc.invalidateQueries({ queryKey: ['word', r.lemma] });
      qc.invalidateQueries({ queryKey: ['words'] });
      if (r.sense_id) {
        qc.invalidateQueries({ queryKey: ['sense', r.sense_id] });
        qc.invalidateQueries({ queryKey: ['attestations', r.sense_id] });
        qc.invalidateQueries({ queryKey: ['pending-usages', r.sense_id] });
      }
    },
  });

  if (own) return <p className="small muted">You sent this one; another moderator must review it.</p>;

  return (
    <div className="review-actions">
      <p className="small muted">
        Contributor <span className="mono">{c.contributor_id.slice(0, 8)}</span>
      </p>
      <Field label="Note to the contributor" hint="Required when rejecting">
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
