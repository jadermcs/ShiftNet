import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { GitFork, LogOut, Plus, Quote, ShieldCheck } from 'lucide-react';
import { fetchMyContributions, signOut, useIsModerator, useSession } from '../lib/contributions';
import { plural } from '../lib/format';
import { ContributionCard } from '../components/ContributionCard';
import { useCrumbs } from '../components/Shell';
import { SignIn } from '../components/SignIn';
import { Empty, ErrorState, Loading } from '../components/States';
import { ValidationBadge } from '../components/ValidationBadge';

/** How contributions are validated, with the badges used across the site. */
export function ValidationLegend() {
  return (
    <dl className="legend-list">
      <div>
        <dt><ValidationBadge state="editorial" /></dt>
        <dd>Loaded and checked by the ShiftNet team.</dd>
      </div>
      <div>
        <dt><ValidationBadge state="automatic" /></dt>
        <dd>A contribution that passed every automatic check and was published at once. A moderator may still confirm it.</dd>
      </div>
      <div>
        <dt><ValidationBadge state="manual" /></dt>
        <dd>A contribution a moderator has checked and accepted.</dd>
      </div>
      <div>
        <dt><ValidationBadge state="pending" /></dt>
        <dd>Flagged by the automatic checks and waiting for a moderator. Not part of the lexicon.</dd>
      </div>
      <div>
        <dt><ValidationBadge state="rejected" /></dt>
        <dd>Turned down by a moderator, with a note saying why.</dd>
      </div>
    </dl>
  );
}

export function Contribute() {
  useCrumbs([{ label: 'Contribute' }]);
  const session = useSession();
  const uid = session?.user.id;
  const mod = useIsModerator(session);
  const mine = useQuery({ queryKey: ['my-contributions', uid], queryFn: () => fetchMyContributions(uid!), enabled: !!uid });

  return (
    <>
      <div className="card page-head">
        <span className="label">Contribute</span>
        <h1 className="h-page">Propose usages, senses and relations</h1>
        <p className="muted">
          Anyone can propose a dated quotation for a sense, a sense that is missing, or a WordNet relation (synonym,
          hypernym, part …) between a sense and another word. Every proposal runs through automatic
          checks (required fields, the word appears in the quote, dates are consistent, the reference is well formed, no
          duplicates). A proposal that passes them all is published straight away; one they flag waits for a moderator.
        </p>
        <details className="legend-details">
          <summary className="small fg2">What the badges mean</summary>
          <ValidationLegend />
        </details>
      </div>

      {session === undefined && <Loading label="Checking sign-in…" />}
      {session === null && <SignIn />}
      {session && (
        <>
          <div className="contribute-bar">
            <span className="small muted">
              Signed in as <span className="fg2">{session.user.email}</span>
            </span>
            <div className="row-gap wrap push-right">
              {mod.data && (
                <Link to="/review" className="btn">
                  <ShieldCheck size={14} aria-hidden="true" />
                  Review queue
                </Link>
              )}
              <Link to="/contribute/usage" className="btn">
                <Quote size={14} aria-hidden="true" />
                Propose a usage
              </Link>
              <Link to="/contribute/relation" className="btn">
                <GitFork size={14} aria-hidden="true" />
                Propose a relation
              </Link>
              <Link to="/contribute/sense" className="btn btn-primary">
                <Plus size={14} aria-hidden="true" />
                Propose a sense
              </Link>
              <button className="btn" onClick={() => signOut()}>
                <LogOut size={14} aria-hidden="true" />
                Sign out
              </button>
            </div>
          </div>
          <section className="stack-8" aria-labelledby="mine-h">
            <div className="group-head">
              <h2 id="mine-h">Your contributions</h2>
              {mine.data && <span className="mono small muted">{plural(mine.data.length, 'contribution')}</span>}
            </div>
            {mine.isPending && <Loading rows={2} />}
            {mine.isError && <ErrorState error={mine.error} retry={() => mine.refetch()} />}
            {mine.data?.length === 0 && (
              <Empty>
                Nothing yet. Open a sense and choose <em>Propose a usage</em>, or propose a sense from a word’s page.
              </Empty>
            )}
            {mine.data?.map((c) => <ContributionCard key={c.id} c={c} />)}
          </section>
        </>
      )}
    </>
  );
}
