import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ChevronRight } from 'lucide-react';
import { fetchHyponyms, fetchSynset, fetchSynsetPath } from '../lib/api';
import { plural, senseTag } from '../lib/format';
import type { PathStep, SenseDetail, SynsetCard, SynsetRef } from '../lib/types';
import { ErrorState, Loading } from './States';

const COLLAPSE_AT = 10;

export const synsetName = (s: SynsetRef) => s.lemmas[0];

/** entity › physical entity › … › current. Every step but the last opens that synset. */
export function TaxonomyPath({ path, current }: { path: PathStep[]; current?: string }) {
  return (
    <ol className="tax-path" aria-label="Hypernym path">
      {path.map((p, i) => {
        const last = i === path.length - 1;
        return (
          <li key={p.id}>
            {last ? (
              <span className="fg tax-current" aria-current="page">
                {current ?? synsetName(p)}
              </span>
            ) : (
              <Link to={`/synset/${encodeURIComponent(p.id)}`} title={p.gloss ?? undefined}>
                {synsetName(p)}
              </Link>
            )}
            {!last && <ChevronRight size={13} className="icon-faint" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}

/** Synsets one level down, oldest dated first. Long lists fold after ten. */
export function HyponymList({ items, label }: { items: SynsetCard[]; label: string }) {
  const [open, setOpen] = useState(false);
  const shown = open ? items : items.slice(0, COLLAPSE_AT);
  return (
    <div className="stack-8">
      <ul className="tax-list" aria-label={label}>
        {shown.map((h) => (
          <li key={h.id}>
            <Link to={`/synset/${encodeURIComponent(h.id)}`} className="tax-row">
              <span className="tax-name">
                <span className="fg">{synsetName(h)}</span>
                {h.lemmas.length > 1 && <span className="muted small"> · {h.lemmas.slice(1).join(', ')}</span>}
              </span>
              <span className="muted small ellipsis tax-gloss">{h.gloss ?? ''}</span>
              <span className="mono small nowrap fg2">
                {h.first_label ?? <span className="sr-only">undated</span>}
              </span>
              <span className="mono small muted nowrap tax-count" title={plural(h.hyponym_count, 'hyponym')}>
                {h.hyponym_count > 0 ? (
                  <>
                    {h.hyponym_count}
                    <ChevronRight size={13} aria-hidden="true" />
                  </>
                ) : (
                  ''
                )}
                <span className="sr-only">{plural(h.hyponym_count, 'hyponym')}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {items.length > COLLAPSE_AT && (
        <button className="rel-chip rel-more tax-more" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </div>
  );
}

/** Where a sense sits in WordNet: its hypernym path, other hypernyms, and the hyponyms below it. */
export function TaxonomyCard({ sense: s }: { sense: SenseDetail }) {
  const id = s.synset_id;
  const path = useQuery({ queryKey: ['synsetPath', id], queryFn: () => fetchSynsetPath(id!), enabled: !!id });
  const synset = useQuery({ queryKey: ['synset', id], queryFn: () => fetchSynset(id!), enabled: !!id });
  const hyponyms = useQuery({ queryKey: ['hyponyms', id], queryFn: () => fetchHyponyms(id!), enabled: !!id });

  const also = synset.data?.hypernyms.filter((h) => h.position > 0) ?? [];
  const failed = [path, synset, hyponyms].find((q) => q.isError);

  return (
    <section className="card relations" aria-labelledby="tax-h">
      <div className="attestations-head">
        <h2 id="tax-h">Taxonomy</h2>
        {id && (
          <Link to={`/synset/${encodeURIComponent(id)}`} className="link-quiet small">
            Open synset
          </Link>
        )}
      </div>
      {!id && <span className="muted">This sense is not placed in the WordNet taxonomy yet.</span>}
      {id && (path.isPending || synset.isPending || hyponyms.isPending) && <Loading label="Loading taxonomy…" />}
      {failed && <ErrorState error={failed.error} retry={() => failed.refetch()} />}
      {path.data && synset.data && hyponyms.data && (
        <>
          {path.data.length > 1 ? (
            <TaxonomyPath path={path.data} current={`${s.lemma} ${senseTag(s)}`} />
          ) : (
            <span className="muted">
              {s.pos === 'adjective' || s.pos === 'adverb'
                ? 'WordNet has no hypernym tree for adjectives and adverbs.'
                : 'No hypernym recorded for this synset.'}
            </span>
          )}
          {also.length > 0 && (
            <div className="rel-group">
              <span className="muted">Also under</span>
              <div className="row-gap-6 wrap">
                {also.map((h) => (
                  <Link key={h.hypernym.id} to={`/synset/${encodeURIComponent(h.hypernym.id)}`} className="rel-chip">
                    {synsetName(h.hypernym)}
                  </Link>
                ))}
              </div>
            </div>
          )}
          {hyponyms.data.length > 0 && (
            <div className="rel-group">
              <span className="muted">
                Hyponyms <span className="mono small">{hyponyms.data.length}</span>
              </span>
              <HyponymList items={hyponyms.data} label={`Hyponyms of ${s.lemma} ${senseTag(s)}`} />
            </div>
          )}
        </>
      )}
    </section>
  );
}
