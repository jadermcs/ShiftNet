import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft } from 'lucide-react';
import { fetchAttestations, fetchChildren, fetchSense, fetchWord } from '../lib/api';
import { branchColor, branchLetter, normalize, plural, senseLabel, senseTag } from '../lib/format';
import { ancestry, layoutLineage, type GraphItem } from '../lib/graph';
import type { Attestation, RelationType, Sense, SenseDetail, SenseRef } from '../lib/types';
import { AttestationList } from '../components/Attestations';
import { SenseContribute } from '../components/ContributeLinks';
import { TaxonomyCard } from '../components/Taxonomy';
import { LineageGraph } from '../components/LineageGraph';
import { ValidationBadge } from '../components/ValidationBadge';
import { ShareBar } from '../components/ShareBar';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';
import { NotFound } from './NotFound';

const RELATION_GROUPS: [RelationType | 'synonym', string][] = [
  ['synonym', 'Synonyms'],
  ['antonym', 'Antonyms'],
  ['hypernym', 'Hypernyms'],
  ['hyponym', 'Hyponyms'],
  ['meronym', 'Meronyms'],
  ['holonym', 'Holonyms'],
  ['derived', 'Derived forms'],
];
const COLLAPSE_AT = 10;

export function SensePage() {
  const id = useParams().id ?? '';
  const sense = useQuery({ queryKey: ['sense', id], queryFn: () => fetchSense(id) });
  const lemma = sense.data?.lemma;
  const word = useQuery({ queryKey: ['word', lemma], queryFn: () => fetchWord(lemma!), enabled: !!lemma });
  const children = useQuery({ queryKey: ['children', id], queryFn: () => fetchChildren(id) });

  const s = sense.data;
  useCrumbs(s ? [{ label: s.lemma, to: `/word/${encodeURIComponent(s.lemma)}` }, { label: senseTag(s) }] : [{ label: id }]);

  if (sense.isPending) return <Loading label="Loading sense…" rows={3} />;
  if (sense.isError) return <ErrorState error={sense.error} retry={() => sense.refetch()} />;
  if (!s) return <NotFound q={id} />;

  const refLabel = (x: SenseRef) => `${senseLabel(x, s.lemma)} · ${x.date_label}`;

  return (
    <>
      <ShareBar title={`${s.lemma}, ${senseTag(s)}: ${s.gloss}`} citeKey={s.id} />
      <div className="sense-layout">
        <div className="stack-16 sense-main">
          <div className="card sense-head">
            <Link to={`/word/${encodeURIComponent(s.lemma)}`} className="back">
              <ArrowLeft size={15} aria-hidden="true" />
              Back to {s.lemma}
            </Link>
            <div className="stack-10">
              <div className="title-row">
                <h1 className="h-sense">{s.lemma}</h1>
                <span className="mono fg2">{senseTag(s)}</span>
                <em className="muted">{s.pos}</em>
              </div>
              <div className="gloss-lg">{s.gloss}</div>
              {s.examples.length > 0 && (
                <div className="examples examples-lg">
                  {s.examples.map((e) => (
                    <em key={e}>“{e}”</em>
                  ))}
                </div>
              )}
            </div>
            <dl className="facts-table">
              <dt>Registered</dt>
              <dd className="mono">{s.date_label}</dd>
              <dt>Date source</dt>
              <dd className="row-gap wrap">
                <span className="source-type">{s.source_type}</span>
                {s.source}
              </dd>
              <dt>Validation</dt>
              <dd>
                <ValidationBadge state={s.validation} />
              </dd>
              <dt>Shift type</dt>
              <dd>
                <span className="chip">{s.shift}</span>
              </dd>
              <dt>Branch</dt>
              <dd className="mono dot-label">
                <span className="dot dot-lg" style={{ background: branchColor(s.branch) }} />
                {branchLetter(s.branch)}
                {s.obsolete_label && <span className="sans muted">· obsolete {s.obsolete_label}</span>}
              </dd>
              <dt>Parent senses</dt>
              <dd className="stack-4">
                {s.parents.length === 0 && <span className="muted">None, root sense</span>}
                {s.parents.map((p) => (
                  <div key={p.parent.id} className="ref">
                    <Link to={`/sense/${p.parent.id}`} className="ref-link">
                      <span className="mono small fg2 nowrap">{refLabel(p.parent)}</span>
                      <span>{p.parent.gloss}</span>
                    </Link>
                    {p.source && <span className="small muted">Link source: {p.source}</span>}
                  </div>
                ))}
              </dd>
              <dt>Child senses</dt>
              <dd className="stack-4">
                {children.isPending && <span className="muted">Loading…</span>}
                {children.isError && <span className="muted">Could not load child senses.</span>}
                {children.data?.length === 0 && <span className="muted">None recorded</span>}
                {children.data?.map((c) => (
                  <Link key={c.id} to={`/sense/${c.id}`} className="ref-link">
                    <span className="mono small fg2 nowrap">{refLabel(c)}</span>
                    <span>{c.gloss}</span>
                  </Link>
                ))}
              </dd>
            </dl>
          </div>
          <Attestations key={`att-${s.id}`} sense={s} />
          <SenseContribute key={`contrib-${s.id}`} senseId={s.id} />
          <TaxonomyCard key={`tax-${s.id}`} sense={s} />
          <Relations key={s.id} sense={s} />
        </div>
        <aside className="card mini" aria-label={`Lineage of ${s.lemma}`}>
          <div className="mini-head">
            <span className="label">Lineage of {s.lemma}</span>
            <Link to={`/word/${encodeURIComponent(s.lemma)}?view=timeline`} className="link-quiet small">
              Full timeline
            </Link>
          </div>
          {word.isPending && <Loading />}
          {word.isError && <ErrorState error={word.error} retry={() => word.refetch()} />}
          {word.data && <MiniLineage senses={word.data} current={s.id} />}
        </aside>
      </div>
    </>
  );
}

type AttestationOrder = 'relevance' | 'date';

/** Every attestation of the sense: most relevant first, or in date order to read the sense's history. */
function Attestations({ sense: s }: { sense: Sense }) {
  const att = useQuery({ queryKey: ['attestations', s.id], queryFn: () => fetchAttestations(s.id) });
  const [order, setOrder] = useState<AttestationOrder>('relevance');
  const ref = useRef<HTMLElement>(null);
  const { hash } = useLocation();

  // "All attestations" links from the word page land here once the list has rendered.
  useEffect(() => {
    if (hash === '#attestations' && att.isSuccess) ref.current?.scrollIntoView({ block: 'start' });
  }, [hash, att.isSuccess]);

  const items = useMemo<Attestation[]>(() => {
    const list = att.data ?? [];
    if (order === 'relevance') return list;
    return [...list].sort((a, b) => (a.year ?? Infinity) - (b.year ?? Infinity) || a.id.localeCompare(b.id));
  }, [att.data, order]);

  return (
    <section id="attestations" ref={ref} className="card attestations-card" aria-labelledby="att-h">
      <div className="attestations-head">
        <h2 id="att-h">
          Attestations {att.data && <span className="mono small muted">{att.data.length}</span>}
        </h2>
        {items.length > 1 && (
          <div className="segmented segmented-sm" role="group" aria-label="Order attestations">
            <button aria-pressed={order === 'relevance'} onClick={() => setOrder('relevance')}>
              Most relevant
            </button>
            <button aria-pressed={order === 'date'} onClick={() => setOrder('date')}>
              Oldest first
            </button>
          </div>
        )}
      </div>
      {att.isPending && <Loading label="Loading attestations…" />}
      {att.isError && <ErrorState error={att.error} retry={() => att.refetch()} />}
      {att.data?.length === 0 && <span className="muted">No attestations recorded for this sense yet.</span>}
      {items.length > 0 && <AttestationList items={items} lemma={s.lemma} />}
      {att.data && att.data.length > 0 && (
        <p className="small muted">
          {plural(att.data.length, 'quotation')} showing this sense in use. Each points to the work it is quoted from and
          says how it was checked: by the ShiftNet team, automatically, or by a moderator.
        </p>
      )}
    </section>
  );
}

/** Relations by word. Hypernyms and hyponyms move to the Taxonomy card once the sense is placed in a synset. */
function Relations({ sense: s }: { sense: SenseDetail }) {
  const inTaxonomy = (type: RelationType | 'synonym') => !!s.synset_id && (type === 'hypernym' || type === 'hyponym');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const groups = RELATION_GROUPS.map(([type, title]) => ({
    type,
    title,
    items:
      type === 'synonym'
        ? s.synonyms.map((x) => x.lemma).filter((w) => normalize(w) !== normalize(s.lemma))
        : s.relations.filter((r) => r.type === type).map((r) => r.target_lemma),
  })).filter((g) => g.items.length && !inTaxonomy(g.type));

  return (
    <section className="card relations" aria-labelledby="rel-h">
      <h2 id="rel-h">Relations</h2>
      {groups.length === 0 && <span className="muted">No relations recorded for this synset.</span>}
      {groups.map((g) => {
        const expanded = open[g.type] || g.items.length <= COLLAPSE_AT;
        return (
          <div key={g.type} className="rel-group">
            <span className="muted">
              {g.title} <span className="mono small">{g.items.length}</span>
            </span>
            <div className="row-gap-6 wrap">
              {(expanded ? g.items : g.items.slice(0, COLLAPSE_AT)).map((w) => (
                <Link key={w} to={`/word/${encodeURIComponent(w)}`} className="rel-chip">
                  {w}
                </Link>
              ))}
              {g.items.length > COLLAPSE_AT && (
                <button className="rel-chip rel-more" aria-expanded={!!open[g.type]} onClick={() => setOpen({ ...open, [g.type]: !open[g.type] })}>
                  {open[g.type] ? 'Show fewer' : `Show all ${g.items.length}`}
                </button>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}

/** The sense within its word's tree, current sense ringed (US6). */
function MiniLineage({ senses, current }: { senses: Sense[]; current: string }) {
  const navigate = useNavigate();
  const [hover, setHover] = useState<string | null>(null);
  const ROW = 34;

  const layout = useMemo(() => {
    const items: GraphItem[] = senses.map((x) => ({
      kind: 'sense',
      h: ROW,
      sense: { id: x.id, parents: x.parents.map((p) => p.parent.id), branch: x.branch, alive: x.obsolete_year == null, dimmed: false },
    }));
    items.push({ kind: 'today', h: 26 });
    return layoutLineage(items, { rowH: ROW, pastDir: -1, extendToToday: true, laneW: 14, pad: 14 });
  }, [senses]);

  const parentsOf = useMemo(() => {
    const m = new Map(senses.map((x) => [x.id, x.parents.map((p) => p.parent.id)]));
    return (id: string) => m.get(id) ?? [];
  }, [senses]);
  const highlight = useMemo(() => ancestry(hover ?? current, parentsOf), [hover, current, parentsOf]);
  const cols = `${layout.width}px minmax(0,1fr)`;

  return (
    <div className="lineage-body" onMouseLeave={() => setHover(null)}>
      <LineageGraph layout={layout} highlight={highlight} current={current} />
      {senses.map((x) => (
        <div
          key={x.id}
          tabIndex={0}
          role="link"
          aria-current={x.id === current ? 'page' : undefined}
          aria-label={`${senseTag(x)}, ${x.date_label}, ${x.gloss}`}
          className={`mini-row${x.id === current ? ' current' : ''}`}
          style={{ gridTemplateColumns: cols, height: ROW }}
          onClick={() => navigate(`/sense/${x.id}`)}
          onKeyDown={(e) => e.key === 'Enter' && navigate(`/sense/${x.id}`)}
          onMouseEnter={() => setHover(x.id)}
          onFocus={() => setHover(x.id)}
        >
          <span />
          <div className="mini-text">
            <span className="mono fg nowrap">
              {senseTag(x)} · {x.date_label}
            </span>
            <span className="muted ellipsis">{x.gloss}</span>
          </div>
        </div>
      ))}
      <div className="mini-row" style={{ gridTemplateColumns: cols, height: 26 }}>
        <span />
        <em className="small muted">still in use today</em>
      </div>
    </div>
  );
}
