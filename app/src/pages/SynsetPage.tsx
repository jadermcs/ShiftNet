import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchHyponyms, fetchSynset, fetchSynsetPath, fetchSynsetSenses } from '../lib/api';
import { senseTag } from '../lib/format';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';
import { HyponymList, TaxonomyPath, synsetName } from '../components/Taxonomy';
import { NotFound } from './NotFound';

/** One node of the WordNet taxonomy: where it sits, its dated senses, and the synsets below it. */
export function SynsetPage() {
  const id = useParams().id ?? '';
  const synset = useQuery({ queryKey: ['synset', id], queryFn: () => fetchSynset(id) });
  const path = useQuery({ queryKey: ['synsetPath', id], queryFn: () => fetchSynsetPath(id) });
  const hyponyms = useQuery({ queryKey: ['hyponyms', id], queryFn: () => fetchHyponyms(id) });
  const senses = useQuery({ queryKey: ['synsetSenses', id], queryFn: () => fetchSynsetSenses(id) });

  const s = synset.data;
  useCrumbs([{ label: 'Taxonomy', to: '/taxonomy' }, { label: s ? synsetName(s) : id }]);

  if (synset.isPending) return <Loading label="Loading synset…" rows={3} />;
  if (synset.isError) return <ErrorState error={synset.error} retry={() => synset.refetch()} />;
  if (!s) return <NotFound q={id} />;

  const also = s.hypernyms.filter((h) => h.position > 0);

  return (
    <>
      <div className="card sense-head">
        <div className="stack-10">
          <div className="title-row">
            <h1 className="h-sense">{synsetName(s)}</h1>
            <em className="muted">{s.pos}</em>
            <span className="mono small muted">{s.id}</span>
          </div>
          {s.lemmas.length > 1 && (
            <div className="synonyms">
              {s.lemmas.slice(1).map((l) => (
                <Link key={l} to={`/word/${encodeURIComponent(l)}`} className="synonym">
                  {l}
                </Link>
              ))}
            </div>
          )}
          {s.gloss && <div className="gloss-lg">{s.gloss}</div>}
        </div>
        {path.isError && <ErrorState error={path.error} retry={() => path.refetch()} />}
        {path.data && path.data.length > 1 && <TaxonomyPath path={path.data} />}
        {path.data?.length === 1 && <span className="muted small">Top of the taxonomy</span>}
        {also.length > 0 && (
          <div className="row-gap-6 wrap small">
            <span className="muted">Also under</span>
            {also.map((h) => (
              <Link key={h.hypernym.id} to={`/synset/${encodeURIComponent(h.hypernym.id)}`} className="rel-chip">
                {synsetName(h.hypernym)}
              </Link>
            ))}
          </div>
        )}
      </div>

      {senses.isError && <ErrorState error={senses.error} retry={() => senses.refetch()} />}
      {senses.data && senses.data.length > 0 && (
        <section className="card relations" aria-labelledby="dated-h">
          <h2 id="dated-h">
            Dated senses <span className="mono small muted">{senses.data.length}</span>
          </h2>
          <div className="stack-4">
            {senses.data.map((x) => (
              <Link key={x.id} to={`/sense/${x.id}`} className="ref-link">
                <span className="mono small fg2 nowrap">
                  {x.lemma} {senseTag(x)} · {x.date_label}
                </span>
                <span>{x.gloss}</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      <section className="card relations" aria-labelledby="hypo-h">
        <h2 id="hypo-h">
          Hyponyms {hyponyms.data && <span className="mono small muted">{hyponyms.data.length}</span>}
        </h2>
        {hyponyms.isPending && <Loading label="Loading hyponyms…" />}
        {hyponyms.isError && <ErrorState error={hyponyms.error} retry={() => hyponyms.refetch()} />}
        {hyponyms.data?.length === 0 && <span className="muted">No hyponyms recorded for this synset.</span>}
        {hyponyms.data && hyponyms.data.length > 0 && (
          <>
            <HyponymList items={hyponyms.data} label={`Hyponyms of ${synsetName(s)}`} />
            <p className="small muted">
              Oldest registered sense first; undated synsets follow by name. The number on the right counts hyponyms one
              level further down.
            </p>
          </>
        )}
      </section>
    </>
  );
}
