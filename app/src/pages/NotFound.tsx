import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { closeSpellings } from '../lib/api';
import { hrefFor } from '../components/SearchBox';
import { useCrumbs } from '../components/Shell';

/** Unknown word or sense, with close spellings. Also used by search when nothing matches. */
export function NotFound({ q, crumb = true }: { q: string; crumb?: boolean }) {
  useCrumbs(crumb ? [{ label: 'Not found' }] : [{ label: 'Search' }, { label: `“${q}”` }]);
  const close = useQuery({ queryKey: ['close', q], queryFn: () => closeSpellings(q), enabled: q.length > 0 });

  return (
    <div className="card notfound">
      <span className="label">Not found</span>
      <h1 className="h-page">No results for “{q}”</h1>
      <p className="muted">The word or sense is not in the lexicon. Check the spelling or try one of these.</p>
      <div className="row-gap wrap">
        {close.isPending && q && <span className="small muted">Looking for close spellings…</span>}
        {(close.data?.length ? close.data : [{ lemma: 'cloud', kind: 'word' as const, sense_id: null }, { lemma: 'mouse', kind: 'word' as const, sense_id: null }]).map(
          (c) => (
            <Link key={c.lemma} className="pill pill-lg" to={hrefFor(c)}>
              {c.lemma}
            </Link>
          ),
        )}
      </div>
      <div className="row-gap notfound-actions">
        <Link to="/" className="btn btn-primary">
          Back to search
        </Link>
        <Link to="/timeline" className="btn">
          Browse the global timeline
        </Link>
      </div>
    </div>
  );
}

export function NotFoundRoute() {
  const last = useLocation().pathname.split('/').filter(Boolean).pop() ?? '';
  let q = last;
  try {
    q = decodeURIComponent(last);
  } catch {
    // keep the raw segment
  }
  return <NotFound q={q} />;
}
