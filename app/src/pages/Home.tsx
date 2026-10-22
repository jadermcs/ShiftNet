import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ChevronRight } from 'lucide-react';
import { fetchRecent } from '../lib/api';
import { index, senseTag } from '../lib/format';
import { SearchBox } from '../components/SearchBox';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';

const TRY = ['cloud', 'mouse', 'web', 'troll', 'nice'];

export function Home() {
  useCrumbs([]);
  const recent = useQuery({ queryKey: ['recent'], queryFn: () => fetchRecent(10) });

  return (
    <div className="home">
      <div className="home-hero">
        <div className="label">Open English WordNet, with dates</div>
        <h1 className="display">Every sense has a date and a parent.</h1>
        <p className="muted lead">
          Search a word to read its synsets, then switch to the timeline to see which meaning grew out of which.
        </p>
      </div>
      <div>
        <SearchBox size="lg" autoFocus placeholder="Search a word or expression" />
        <div className="try">
          Try
          {TRY.map((w) => (
            <Link key={w} className="pill" to={`/word/${w}?view=timeline`}>
              {w}
            </Link>
          ))}
        </div>
      </div>
      <section className="stack-10" aria-labelledby="recent-h">
        <div className="section-head">
          <h2 id="recent-h">Latest registered senses</h2>
        </div>
        {recent.isPending && <Loading rows={4} />}
        {recent.isError && <ErrorState error={recent.error} retry={() => recent.refetch()} />}
        {recent.data?.map((s, i) => (
          <Link key={s.id} to={`/sense/${s.id}`} className="card index-row">
            <span className="index">{index(i + 1, 3)}</span>
            <span className="index-rule" />
            <span className="index-body">
              <span>
                <strong>{s.lemma}</strong> <span className="mono small muted">{senseTag(s)}</span>
              </span>
              <span className="ellipsis small muted">{s.gloss}</span>
            </span>
            <span className="mono small fg2">{s.date_label}</span>
            <ChevronRight size={16} className="icon-faint" aria-hidden="true" />
          </Link>
        ))}
      </section>
    </div>
  );
}
