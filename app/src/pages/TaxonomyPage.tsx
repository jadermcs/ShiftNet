import { useQuery } from '@tanstack/react-query';
import { fetchTaxonomyRoots } from '../lib/api';
import { cap } from '../lib/format';
import { POS_ORDER } from '../lib/types';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';
import { HyponymList } from '../components/Taxonomy';

/** Entry point to the WordNet taxonomy: the top synsets of each part of speech. */
export function TaxonomyPage() {
  useCrumbs([{ label: 'Taxonomy' }]);
  const roots = useQuery({ queryKey: ['taxonomyRoots'], queryFn: fetchTaxonomyRoots });

  return (
    <>
      <div className="card page-head">
        <h1 className="h-page">Taxonomy</h1>
        <p className="muted">
          Browse WordNet from the top down, following hypernym links. Under each synset, hyponyms are listed by the date
          their oldest sense was registered, so you can see when a part of the tree filled up.
        </p>
      </div>
      {roots.isPending && <Loading label="Loading taxonomy…" rows={2} />}
      {roots.isError && <ErrorState error={roots.error} retry={() => roots.refetch()} />}
      {roots.data?.length === 0 && <div className="card state muted">No synsets loaded yet.</div>}
      {POS_ORDER.map((pos) => {
        const items = roots.data?.filter((r) => r.pos === pos) ?? [];
        if (!items.length) return null;
        return (
          <section key={pos} className="card relations" aria-labelledby={`roots-${pos}`}>
            <h2 id={`roots-${pos}`}>{cap(pos)}s</h2>
            {pos === 'verb' && (
              <p className="small muted">WordNet verbs have no single top; each tree starts from a general verb.</p>
            )}
            <HyponymList items={items} label={`Top ${pos} synsets`} />
          </section>
        );
      })}
    </>
  );
}
