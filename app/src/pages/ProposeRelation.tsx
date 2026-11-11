import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Sparkles, X } from 'lucide-react';
import { fetchSense, fetchWord } from '../lib/api';
import {
  ChecksFailed,
  RELATION_KINDS,
  RELATION_LABELS,
  checkRelation,
  compact,
  fetchRelationSuggestions,
  submitRelation,
  type Check,
  type Contribution,
  type RelationKind,
  type RelationProposal,
  type RelationSuggestion,
} from '../lib/contributions';
import { senseTag } from '../lib/format';
import type { SenseDetail } from '../lib/types';
import { Field, errorFor } from '../components/Field';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';
import { SubmitBar, SubmitResult } from '../components/SubmitBar';
import { ValidationBadge } from '../components/ValidationBadge';
import { SensePicker } from './ProposeUsage';

export function ProposeRelation() {
  const [params, setParams] = useSearchParams();
  const senseId = params.get('sense');
  const sense = useQuery({ queryKey: ['sense', senseId], queryFn: () => fetchSense(senseId!), enabled: !!senseId });
  const s = sense.data;
  useCrumbs([
    { label: 'Contribute', to: '/contribute' },
    ...(s ? [{ label: s.lemma, to: `/word/${encodeURIComponent(s.lemma)}` }, { label: senseTag(s), to: `/sense/${s.id}` }] : []),
    { label: 'Propose a relation' },
  ]);

  return (
    <>
      <div className="card page-head">
        <span className="label">Contribute</span>
        <h1 className="h-page">Propose a relation</h1>
        <p className="muted">
          Link a sense to another word, as WordNet does: a broader term (hypernym), a narrower one (hyponym), a synonym, a
          part (meronym) or the whole it belongs to (holonym), an antonym or a derived form. The LexSPLADE encoder suggests
          relations for each sense; pick one or enter your own.
        </p>
      </div>
      {!senseId ? (
        <SensePicker title="Which sense is the relation for?" onPick={(id) => setParams({ sense: id })} />
      ) : sense.isPending ? (
        <Loading label="Loading sense…" />
      ) : sense.isError ? (
        <ErrorState error={sense.error} retry={() => sense.refetch()} />
      ) : !s ? (
        <>
          <p className="card state" role="alert">
            There is no sense <span className="mono">{senseId}</span>.
          </p>
          <SensePicker title="Which sense is the relation for?" onPick={(id) => setParams({ sense: id })} />
        </>
      ) : (
        <>
          <div className="card propose-target">
            <span className="label">Sense</span>
            <div className="row-gap wrap">
              <Link to={`/sense/${s.id}`} className="strong-lg">
                {s.lemma} <span className="mono fg2">{senseTag(s)}</span>
              </Link>
              <ValidationBadge state={s.validation} compact={s.validation === 'editorial'} />
              <button className="link-btn underline small push-right" onClick={() => setParams({})}>
                Choose another sense
              </button>
            </div>
            <div className="gloss">{s.gloss}</div>
            <Recorded s={s} />
          </div>
          <RelationForm key={s.id} sense={s} />
        </>
      )}

    </>
  );
}

/** What the sense already has, so contributors do not propose it again. */
function Recorded({ s }: { s: SenseDetail }) {
  const synonyms = s.synonyms.map((x) => x.lemma).filter((l) => l !== s.lemma);
  if (!synonyms.length && !s.relations.length) return <p className="small muted">No relations recorded yet.</p>;
  return (
    <dl className="relation-recorded small">
      {synonyms.length > 0 && (
        <div>
          <dt>synonyms</dt>
          <dd>{synonyms.join(', ')}</dd>
        </div>
      )}
      {RELATION_KINDS.filter((k) => k !== 'synonym').map((k) => {
        const items = s.relations.filter((r) => r.type === k).map((r) => r.target_lemma);
        return items.length ? (
          <div key={k}>
            <dt>{RELATION_LABELS[k].name.toLowerCase()}s</dt>
            <dd>{items.join(', ')}</dd>
          </div>
        ) : null;
      })}
    </dl>
  );
}

const EMPTY = (senseId: string): RelationProposal => ({ sense_id: senseId, type: '', target_lemma: '' });

function RelationForm({ sense }: { sense: SenseDetail }) {
  const qc = useQueryClient();
  const [p, setP] = useState<RelationProposal>(EMPTY(sense.id));
  const [lookup, setLookup] = useState('');
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Contribution | null>(null);
  const targets = useQuery({ queryKey: ['word', lookup], queryFn: () => fetchWord(lookup), enabled: lookup.length >= 2 });

  const set = (patch: Partial<RelationProposal>) => {
    setP((old) => ({ ...old, ...patch }));
    setChecks(null);
  };
  const useSuggestion = (x: RelationSuggestion) => {
    setP({
      sense_id: sense.id,
      type: x.type,
      target_lemma: x.target_lemma,
      target_sense_id: x.target_sense_id ?? undefined,
      target_synset_id: x.target_synset_id ?? undefined,
    });
    setLookup(x.target_lemma.toLowerCase());
    setChecks(null);
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof ChecksFailed) setChecks(e.checks);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const c = await submitRelation(compact(p));
      setDone(c);
      qc.invalidateQueries(); // an auto-accepted proposal changes the lexicon: refetch every view
    });
  };

  if (done)
    return (
      <SubmitResult
        c={done}
        onAnother={() => {
          setDone(null);
          setChecks(null);
          setP(EMPTY(sense.id));
        }}
      />
    );

  const kind = p.type ? RELATION_LABELS[p.type] : null;
  const choices = targets.data ?? [];
  return (
    <div className="relation-layout">
      <form className="card form-card" onSubmit={onSubmit} aria-label="Proposed relation">
        <div className="form-row">
          <Field label="Relation" required hint={kind?.hint} error={errorFor(checks ?? undefined, 'relation_type')}>
            <select className="input" value={p.type} onChange={(e) => set({ type: e.target.value as RelationKind | '' })}>
              <option value="">Choose…</option>
              {RELATION_KINDS.map((k) => (
                <option key={k} value={k}>
                  {RELATION_LABELS[k].name}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Related word"
            required
            hint="A word or expression, as written in a dictionary."
            error={errorFor(checks ?? undefined, 'target_given', 'target_form', 'not_self', 'not_duplicate')}
          >
            <input
              className="input"
              value={p.target_lemma}
              autoComplete="off"
              onChange={(e) => set({ target_lemma: e.target.value, target_sense_id: undefined, target_synset_id: undefined })}
              onBlur={() => setLookup(p.target_lemma.trim().toLowerCase())}
            />
          </Field>
        </div>

        {p.target_synset_id && (
          <p className="small fg2 row-gap">
            In the taxonomy as{' '}
            <Link to={`/synset/${encodeURIComponent(p.target_synset_id)}`} className="mono inline-link">
              {p.target_synset_id}
            </Link>
            <button type="button" className="link-btn small" onClick={() => set({ target_synset_id: undefined })} aria-label="Do not link the synset">
              <X size={12} aria-hidden="true" />
            </button>
          </p>
        )}
        {choices.length > 0 && (
          <fieldset className="field field-wide">
            <legend className="field-label">
              Which sense of “{lookup}”? <span className="muted small">(optional)</span>
            </legend>
            {errorFor(checks ?? undefined, 'target_sense') && <span className="field-error">{errorFor(checks ?? undefined, 'target_sense')}</span>}
            <ul className="choice-list">
              {choices.map((x) => (
                <li key={x.id}>
                  <label className="choice">
                    <input
                      type="radio"
                      name="target-sense"
                      checked={p.target_sense_id === x.id}
                      onChange={() => set({ target_sense_id: x.id, target_synset_id: undefined })}
                    />
                    <span className="mono small fg2 nowrap">{senseTag(x)}</span>
                    <span>{x.gloss}</span>
                  </label>
                </li>
              ))}
              {p.target_sense_id && (
                <li>
                  <button type="button" className="link-btn underline small" onClick={() => set({ target_sense_id: undefined })}>
                    Any sense
                  </button>
                </li>
              )}
            </ul>
          </fieldset>
        )}

        <Field label="Note for the moderator" wide hint="Why this relation holds, or a dictionary that records it.">
          <textarea className="input" rows={2} maxLength={500} value={p.note ?? ''} onChange={(e) => set({ note: e.target.value })} />
        </Field>
        <SubmitBar busy={busy} checks={checks} error={error} onCheck={() => run(async () => setChecks(await checkRelation(compact(p))))} />
      </form>
      <Suggestions senseId={sense.id} onUse={useSuggestion} />
    </div>
  );
}

/** The encoder's suggestions for the sense, grouped by relation, each a one-click start for the form. */
function Suggestions({ senseId, onUse }: { senseId: string; onUse: (x: RelationSuggestion) => void }) {
  const q = useQuery({ queryKey: ['relation-suggestions', senseId], queryFn: () => fetchRelationSuggestions(senseId) });
  const groups = RELATION_KINDS.map((k) => [k, (q.data ?? []).filter((x) => x.type === k)] as const).filter(([, xs]) => xs.length);
  return (
    <aside className="card relation-suggestions" aria-labelledby="sugg-h">
      <h2 id="sugg-h" className="form-title row-gap">
        <Sparkles size={15} aria-hidden="true" />
        Suggested by LexSPLADE
      </h2>
      <p className="small muted">
        Found by reading the sense’s gloss and examples with a contextual word encoder. A score of 0.6 or more counts as
        support in the automatic checks. Suggested synonyms can be sister terms (mouse → rat): they always go to a moderator.
      </p>
      {q.isPending && <Loading rows={2} />}
      {q.isError && <ErrorState error={q.error} retry={() => q.refetch()} />}
      {q.data?.length === 0 && <p className="small muted">No suggestions for this sense yet.</p>}
      {groups.map(([k, xs]) => (
        <section key={k} className="stack-4">
          <h3 className="label">{RELATION_LABELS[k].name}s</h3>
          <ul className="suggestion-list">
            {xs.slice(0, 6).map((x) => (
              <li key={x.id}>
                <button type="button" className="choice suggestion-row" onClick={() => onUse(x)} aria-label={`Use ${k} ${x.target_lemma}`}>
                  <span>{x.target_lemma}</span>
                  {(x.target_sense_id || x.target_synset_id) && (
                    <span className="mono small muted">{x.target_sense_id ?? x.target_synset_id}</span>
                  )}
                  <span className={`mono small push-right ${x.score >= 0.6 ? 'fg2' : 'muted'}`}>{x.score.toFixed(2)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </aside>
  );
}
