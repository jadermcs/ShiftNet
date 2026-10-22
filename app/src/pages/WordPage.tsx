import { useMemo } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Calendar, ChevronRight, GitBranch, History, List, Tag } from 'lucide-react';
import { fetchWord, resolveLemma, TOP_ATTESTATIONS } from '../lib/api';
import { branchColor, branchLetter, cap, CURRENT_YEAR, index, plural, senseLabel } from '../lib/format';
import { matchesFilters, toSearch, useViewParams, type ViewParams } from '../lib/params';
import { POS_ORDER, type Sense } from '../lib/types';
import { AttestationList } from '../components/Attestations';
import { WordContribute } from '../components/ContributeLinks';
import { FilterBar } from '../components/FilterBar';
import { ValidationBadge } from '../components/ValidationBadge';
import { LineageTable, type LineageRow } from '../components/LineageTable';
import { hrefFor } from '../components/SearchBox';
import { ShareBar } from '../components/ShareBar';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';
import { NotFound } from './NotFound';

export function WordPage() {
  const lemma = useParams().lemma ?? '';
  const [params, update] = useViewParams();
  const word = useQuery({ queryKey: ['word', lemma], queryFn: () => fetchWord(lemma) });
  const missing = word.isSuccess && word.data.length === 0;
  // Not a head word: maybe a different case/accent, or a multi-word expression.
  const resolved = useQuery({ queryKey: ['resolve', lemma], queryFn: () => resolveLemma(lemma), enabled: missing });

  useCrumbs([{ label: lemma, to: `/word/${encodeURIComponent(lemma)}` }, { label: cap(params.view) }]);

  if (word.isPending || (missing && resolved.isPending)) return <Loading label={`Loading ${lemma}…`} rows={4} />;
  if (word.isError) return <ErrorState error={word.error} retry={() => word.refetch()} />;
  if (missing) {
    const r = resolved.data;
    if (r && !(r.kind === 'word' && r.lemma === lemma)) return <Navigate replace to={hrefFor(r) + (r.kind === 'word' ? toSearch(params) : '')} />;
    return <NotFound q={lemma} />;
  }

  const senses = word.data;
  const pos = POS_ORDER.filter((p) => senses.some((s) => s.pos === p));

  return (
    <>
      <div className="card word-head">
        <Link to="/" className="back">
          <ArrowLeft size={15} aria-hidden="true" />
          Back to Home
        </Link>
        <div className="word-head-row">
          <div className="stack-8">
            <h1 className="h-lemma">{lemma}</h1>
            <div className="facts">
              <span>
                <Tag size={14} aria-hidden="true" />
                {pos.join(' · ')}
              </span>
              <span>
                <GitBranch size={14} aria-hidden="true" />
                {plural(senses.length, 'sense')}
              </span>
              <span>
                <Calendar size={14} aria-hidden="true" />
                <span className="mono">
                  {senses[0].date_label} – {senses[senses.length - 1].date_label}
                </span>
              </span>
            </div>
          </div>
          <div role="tablist" aria-label="View" className="segmented">
            <button role="tab" aria-selected={params.view === 'senses'} onClick={() => update({ view: 'senses' })}>
              <List size={14} aria-hidden="true" />
              Senses
            </button>
            <button role="tab" aria-selected={params.view === 'timeline'} onClick={() => update({ view: 'timeline' })}>
              <GitBranch size={14} aria-hidden="true" />
              Timeline
            </button>
          </div>
        </div>
      </div>
      <ShareBar title={lemma} citeKey={lemma} />
      {params.view === 'senses' ? (
        <SensesView senses={senses} lemma={lemma} />
      ) : (
        <TimelineView senses={senses} params={params} update={update} />
      )}
      <WordContribute lemma={lemma} />
    </>
  );
}

/** en-word.net style: senses grouped by part of speech (US3). */
function SensesView({ senses, lemma }: { senses: Sense[]; lemma: string }) {
  return (
    <>
      {POS_ORDER.filter((p) => senses.some((s) => s.pos === p)).map((p) => {
        const list = senses.filter((s) => s.pos === p);
        return (
          <section key={p} className="stack-8" aria-labelledby={`pos-${p}`}>
            <div className="group-head">
              <h2 id={`pos-${p}`}>{cap(p)}</h2>
              <span className="mono small muted">{plural(list.length, 'sense')}</span>
            </div>
            {list.map((s) => (
              <article key={s.id} className="card sense-card">
                <span className="index">{index(s.sense_num, 2)}</span>
                <span className="index-rule" />
                <div className="stack-8 min0">
                  <div className="synonyms">
                    {s.synonyms.map((y) => (
                      <Link key={y.lemma} to={`/word/${encodeURIComponent(y.lemma)}`} className="synonym">
                        {y.lemma}
                      </Link>
                    ))}
                  </div>
                  <div className="gloss">{s.gloss}</div>
                  {s.examples.length > 0 && (
                    <div className="examples">
                      {s.examples.map((e) => (
                        <em key={e}>“{e}”</em>
                      ))}
                    </div>
                  )}
                  <SenseAttestations sense={s} />
                  <div className="sense-meta">
                    <span className="mono fg2 dot-label">
                      <span className="dot" style={{ background: branchColor(s.branch) }} />
                      branch {branchLetter(s.branch)}
                    </span>
                    <span className="mono fg2">registered {s.date_label}</span>
                    <span className="chip">{s.shift}</span>
                    <span>
                      {s.parents.length ? `from ${s.parents.map((x) => senseLabel(x.parent, lemma)).join(' + ')}` : 'root sense'}
                    </span>
                    {s.obsolete_label && <span className="fg2">obsolete {s.obsolete_label}</span>}
                    {s.validation !== 'editorial' && <ValidationBadge state={s.validation} />}
                    <Link to={`/sense/${s.id}`} className="link-quiet push-right">
                      Sense detail
                      <ChevronRight size={14} aria-hidden="true" />
                    </Link>
                  </div>
                </div>
              </article>
            ))}
          </section>
        );
      })}
    </>
  );
}

/** The most relevant attestations of a sense, with a link to the rest on the sense page. */
function SenseAttestations({ sense: s }: { sense: Sense }) {
  const top = s.top_attestations ?? [];
  const total = s.attestation_count ?? top.length;
  if (!top.length) return null;
  return (
    <section className="stack-4" aria-label={`Attestations of ${s.lemma}, ${s.pos} sense ${s.sense_num}`}>
      <span className="label">{total > TOP_ATTESTATIONS ? `Top ${TOP_ATTESTATIONS} of ${total} attestations` : 'Attestations'}</span>
      <AttestationList items={top} lemma={s.lemma} compact />
      {total > top.length && (
        <Link to={`/sense/${s.id}#attestations`} className="link-quiet small">
          All {total} attestations
          <ChevronRight size={13} aria-hidden="true" />
        </Link>
      )}
    </section>
  );
}

/** Senses by registration date with the lineage graph (US4), time travel (US8) and filters (US9). */
function TimelineView({
  senses,
  params,
  update,
}: {
  senses: Sense[];
  params: ViewParams;
  update: (p: Partial<ViewParams>) => void;
}) {
  const first = senses[0].date_earliest;
  const at = params.at == null ? CURRENT_YEAR : Math.max(first, Math.min(CURRENT_YEAR, params.at));
  const asc = params.order === 'asc';

  const rows = useMemo<LineageRow[]>(() => {
    const visible = senses
      .filter((s) => s.date_earliest <= at)
      .sort((a, b) => (asc ? 1 : -1) * (a.date_earliest - b.date_earliest || a.id.localeCompare(b.id)));
    const out: LineageRow[] = visible.map((s) => ({
      kind: 'sense',
      sense: s,
      alive: !(s.obsolete_year != null && s.obsolete_year <= at),
      matches: matchesFilters(params, s),
    }));
    const today: LineageRow = { kind: 'today', label: at >= CURRENT_YEAR ? 'still in use today' : `in use in ${at}` };
    return asc ? [...out, today] : [today, ...out];
  }, [senses, at, asc, params]);

  const hidden = senses.filter((s) => s.date_earliest > at).length;
  const pos = POS_ORDER.filter((p) => senses.some((s) => s.pos === p));

  return (
    <>
      <FilterBar
        params={params}
        update={update}
        posOptions={pos}
        note={hidden > 0 ? `${plural(hidden, 'sense')} registered after ${at} hidden. Senses obsolete by then are shown hollow.` : null}
      >
        <label className="control">
          <History size={15} className="icon-muted" aria-hidden="true" />
          As of
          <input
            type="range"
            min={first}
            max={CURRENT_YEAR}
            step={1}
            value={at}
            aria-label="Time travel date"
            aria-valuetext={at >= CURRENT_YEAR ? 'today' : String(at)}
            onChange={(e) => {
              const v = Number(e.target.value);
              update({ at: v >= CURRENT_YEAR ? null : v });
            }}
          />
          <span className="mono small fg at-label">{at >= CURRENT_YEAR ? 'Today' : at}</span>
        </label>
        <div className="segmented segmented-sm" role="group" aria-label="Order">
          <button aria-pressed={asc} onClick={() => update({ order: 'asc' })}>
            Oldest first
          </button>
          <button aria-pressed={!asc} onClick={() => update({ order: 'desc' })}>
            Newest first
          </button>
        </div>
      </FilterBar>
      <LineageTable rows={rows} pastDir={asc ? -1 : 1} extendToToday />
    </>
  );
}
