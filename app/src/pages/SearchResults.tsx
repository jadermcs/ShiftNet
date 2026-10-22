import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ChevronRight } from 'lucide-react';
import { searchLemmas } from '../lib/api';
import { index, normalize, plural } from '../lib/format';
import { hrefFor } from '../components/SearchBox';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';
import { NotFound } from './NotFound';

export function SearchResults() {
  const q = useParams().q ?? '';
  const res = useQuery({ queryKey: ['search', normalize(q)], queryFn: () => searchLemmas(q, 50) });
  const tooShort = normalize(q).length < 2;
  const empty = tooShort || (res.isSuccess && res.data.length === 0);
  useCrumbs([{ label: 'Search' }, { label: `“${q}”` }]);

  if (empty) return <NotFound q={q} crumb={false} />;
  if (res.isPending) return <Loading label={`Searching for “${q}”…`} rows={3} />;
  if (res.isError) return <ErrorState error={res.error} retry={() => res.refetch()} />;

  return (
    <>
      <div className="card page-head">
        <h1 className="h-page">Results for “{q}”</h1>
        <span className="muted">{plural(res.data.length, 'match', 'matches')}</span>
      </div>
      {res.data.map((s, i) => (
        <Link key={`${s.kind}:${s.lemma}`} to={hrefFor(s)} className="card index-row">
          <span className="index">{index(i + 1, 2)}</span>
          <span className="index-rule" />
          <span className="index-body">
            <span className="strong-lg">{s.lemma}</span>
            <em className="small muted">{s.pos}</em>
          </span>
          <span className="mono small fg2">{s.meta}</span>
          <ChevronRight size={16} className="icon-faint" aria-hidden="true" />
        </Link>
      ))}
    </>
  );
}
