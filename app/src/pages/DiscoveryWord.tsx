import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BookOpen, Check, ExternalLink, GitMerge, Plus, X } from 'lucide-react';
import { fetchWord } from '../lib/api';
import {
  fetchDiscoveryWord,
  matchCandidate,
  promoteCandidate,
  rejectCandidate,
  type Candidate,
  type CorpusUsage,
} from '../lib/discovery';
import { senseTag } from '../lib/format';
import { hostOf } from '../lib/reference';
import { POS_ORDER, SHIFT_TYPES, type Pos, type Sense, type ShiftType } from '../lib/types';
import { Field } from '../components/Field';
import { useCrumbs } from '../components/Shell';
import { Empty, ErrorState, Loading } from '../components/States';
import { YearBars } from '../components/YearBars';

const STATUS_LABEL: Record<Candidate['status'], string> = {
  pending: 'To review',
  matched: 'Matched',
  promoted: 'New sense',
  rejected: 'Rejected',
};

/** A word's candidate senses from sense discovery, with the review actions. */
export function DiscoveryWord() {
  const lemma = useParams().lemma ?? '';
  useCrumbs([{ label: 'Discovery', to: '/discovery' }, { label: lemma }]);
  const word = useQuery({ queryKey: ['discovery-word', lemma], queryFn: () => fetchDiscoveryWord(lemma) });
  const senses = useQuery({ queryKey: ['word', lemma], queryFn: () => fetchWord(lemma) });

  if (word.isPending) return <Loading label="Loading candidates…" rows={3} />;
  if (word.isError) return <ErrorState error={word.error} retry={() => word.refetch()} />;
  const w = word.data;
  if (!w) return <Empty>Sense discovery has not run on “{lemma}”.</Empty>;

  const usages = w.runs.reduce((s, r) => s + r.usage_count, 0);
  const noise = w.runs.reduce((s, r) => s + r.noise_count, 0);
  const pending = w.candidates.filter((c) => c.status === 'pending').length;
  const forms = [...new Set(w.runs.flatMap((r) => r.forms))];
  const lexicon = senses.data ?? [];

  return (
    <>
      <div className="card word-head">
        <span className="label">Discovered senses</span>
        <div className="word-head-row">
          <h1 className="h-lemma">{w.lemma}</h1>
          {lexicon.length > 0 ? (
            <Link to={`/word/${encodeURIComponent(w.lemma)}`} className="btn btn-sm">
              <BookOpen size={13} aria-hidden="true" />
              {lexicon.length} {lexicon.length === 1 ? 'sense' : 'senses'} in the lexicon
            </Link>
          ) : (
            <span className="small muted">Not in the lexicon yet</span>
          )}
        </div>
        <div className="facts">
          <span>
            {w.candidates.length} candidates, {pending} to review
          </span>
          <span>
            {usages.toLocaleString()} usages clustered, {noise.toLocaleString()} left out
          </span>
          <span className="mono small">forms: {forms.join(', ')}</span>
        </div>
      </div>

      {w.candidates.map((c, i) => (
        <CandidateCard key={c.id} c={c} n={i + 1} total={usages} lemma={w.lemma} lexicon={lexicon} />
      ))}
    </>
  );
}

function CandidateCard({ c, n, total, lemma, lexicon }: { c: Candidate; n: number; total: number; lemma: string; lexicon: Sense[] }) {
  const [more, setMore] = useState(false);
  const shown = more ? c.typical_usages : c.typical_usages.slice(0, 4);
  const share = total ? Math.round((100 * c.size) / total) : 0;

  return (
    <section className={`card candidate${c.status !== 'pending' ? ' candidate-decided' : ''}`} aria-labelledby={`cand-${c.id}`}>
      <div className="candidate-head">
        <h2 id={`cand-${c.id}`} className="small-h">
          Candidate {n} <span className="mono small muted">· {c.size.toLocaleString()} usages ({share}%)</span>
        </h2>
        <span className={`chip chip-sm candidate-status-${c.status}`}>{STATUS_LABEL[c.status]}</span>
      </div>

      <div className="candidate-body">
        <div className="stack-10 min0">
          <div className="candidate-terms" aria-label="Strongest terms">
            {c.terms.slice(0, 14).map((t) => (
              <span key={t.term} className="chip chip-sm" title={`weight ${t.weight.toFixed(3)}`}>
                {t.term}
              </span>
            ))}
          </div>
          {c.nearest_sense_id && (
            <p className="small fg2">
              Closest sense in the lexicon:{' '}
              <Link to={`/sense/${c.nearest_sense_id}`} className="inline-link">
                {lemma} {c.nearest_pos ? senseTag({ pos: c.nearest_pos, sense_num: c.nearest_sense_num ?? 0 }) : c.nearest_sense_id}
              </Link>{' '}
              <span className="muted">“{c.nearest_gloss}”</span>{' '}
              <span className="mono muted">similarity {c.nearest_score?.toFixed(2)}</span>
            </p>
          )}
        </div>
        <YearBars counts={c.year_counts} label={`Candidate ${n} usages per crawl year`} />
      </div>

      <div className="stack-8">
        <h3 className="label">Most typical usages</h3>
        <ol className="usage-list">
          {shown.map((u) => (
            <UsageLine key={u.id} u={u} />
          ))}
        </ol>
        {c.typical_usages.length > 4 && (
          <button className="link-btn underline small" onClick={() => setMore(!more)}>
            {more ? 'Fewer usages' : `${c.typical_usages.length - 4} more typical usages`}
          </button>
        )}
        {c.borderline_usages.length > 0 && (
          <details>
            <summary className="small fg2">Borderline usages (least like the rest)</summary>
            <ol className="usage-list">
              {c.borderline_usages.map((u) => (
                <UsageLine key={u.id} u={u} />
              ))}
            </ol>
          </details>
        )}
      </div>

      {c.status === 'pending' ? <ReviewPanel c={c} lexicon={lexicon} /> : <Outcome c={c} />}
    </section>
  );
}

function UsageLine({ u }: { u: CorpusUsage }) {
  const host = u.url ? hostOf(u.url) : null;
  return (
    <li className="usage">
      <p className="attestation-quote">
        {u.context.slice(0, u.target_start)}
        <mark>{u.context.slice(u.target_start, u.target_end)}</mark>
        {u.context.slice(u.target_end)}
      </p>
      <div className="attestation-ref">
        {u.crawled_on && <span className="mono">crawled {u.crawled_on}</span>}
        {u.url && (
          <a href={u.url} target="_blank" rel="noreferrer" className="link-quiet">
            {host} <ExternalLink size={11} aria-hidden="true" className="inline-icon" />
          </a>
        )}
        {u.similarity != null && <span className="mono">typicality {u.similarity.toFixed(2)}</span>}
      </div>
    </li>
  );
}

function Outcome({ c }: { c: Candidate }) {
  return (
    <p className="small fg2 candidate-outcome">
      {c.status === 'matched' && c.sense_id && (
        <>
          Matched to <Link to={`/sense/${c.sense_id}`} className="inline-link mono">{c.sense_id}</Link>.
        </>
      )}
      {c.status === 'promoted' && c.sense_id && (
        <>
          Added to the lexicon as <Link to={`/sense/${c.sense_id}`} className="inline-link mono">{c.sense_id}</Link>.
        </>
      )}
      {c.status === 'rejected' && 'Rejected.'}
      {c.review_note && <span className="muted"> Note: {c.review_note}</span>}
    </p>
  );
}

type Action = 'match' | 'promote' | 'reject';

function ReviewPanel({ c, lexicon }: { c: Candidate; lexicon: Sense[] }) {
  const qc = useQueryClient();
  const firstYear = c.first_seen ? Number(c.first_seen.slice(0, 4)) : new Date().getFullYear();
  const [action, setAction] = useState<Action>(lexicon.length ? 'match' : 'promote');
  const [senseId, setSenseId] = useState(c.nearest_sense_id ?? lexicon[0]?.id ?? '');
  const [pos, setPos] = useState<Pos>(c.nearest_pos ?? 'noun');
  const [gloss, setGloss] = useState('');
  const [parent, setParent] = useState('');
  const [shift, setShift] = useState<ShiftType>('metaphor');
  const [dateLabel, setDateLabel] = useState(String(firstYear));
  const [dateYear, setDateYear] = useState(String(firstYear));
  const [note, setNote] = useState('');

  const review = useMutation({
    mutationFn: () => {
      const n = note.trim() || undefined;
      if (action === 'match') return matchCandidate(c.id, { sense_id: senseId.trim() || undefined, note: n });
      if (action === 'reject') return rejectCandidate(c.id, note.trim());
      return promoteCandidate(c.id, {
        pos,
        gloss: gloss.trim(),
        parent_ids: parent.trim() ? [parent.trim()] : [],
        shift: parent.trim() ? shift : 'root',
        date_label: dateLabel.trim() || undefined,
        date_earliest: Number(dateYear) || undefined,
        note: n,
      });
    },
    // A review can touch a sense, its attestations, the dominance chart, the word list and the stats:
    // refetch everything rather than track each cached view.
    onSuccess: () => qc.invalidateQueries(),
  });

  const ready =
    action === 'match' ? !!senseId.trim() : action === 'reject' ? !!note.trim() : gloss.trim().length >= 3 && !!dateYear;

  return (
    <div className="candidate-review">
      <div role="radiogroup" aria-label="Decision" className="segmented segmented-sm">
        {([
          ['match', 'Existing sense', GitMerge],
          ['promote', 'New sense', Plus],
          ['reject', 'Reject', X],
        ] as const).map(([id, label, Icon]) => (
          <button key={id} role="radio" aria-checked={action === id} onClick={() => setAction(id)}>
            <Icon size={13} aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>

      {action === 'match' && (
        <div className="form-grid">
          <Field label="Sense" required hint="Its 3 most typical usages are quoted as attestations of that sense.">
            {lexicon.length ? (
              <select className="input" value={senseId} onChange={(e) => setSenseId(e.target.value)}>
                {lexicon.map((s) => (
                  <option key={s.id} value={s.id}>
                    {senseTag(s)} · {s.gloss}
                  </option>
                ))}
              </select>
            ) : (
              <input className="input mono" placeholder="sense id, e.g. cloud.n.02" value={senseId} onChange={(e) => setSenseId(e.target.value)} />
            )}
          </Field>
        </div>
      )}

      {action === 'promote' && (
        <div className="form-grid">
          <Field label="Part of speech" required>
            <select className="input" value={pos} onChange={(e) => setPos(e.target.value as Pos)}>
              {POS_ORDER.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </Field>
          <Field label="Gloss" required wide hint="A WordNet-style definition of this use of the word.">
            <textarea className="input textarea" rows={2} maxLength={300} value={gloss} onChange={(e) => setGloss(e.target.value)} />
          </Field>
          <Field label="Parent sense" hint="The sense it grew from; none for a root sense.">
            <select className="input" value={parent} onChange={(e) => setParent(e.target.value)}>
              <option value="">None (root sense)</option>
              {lexicon.map((s) => (
                <option key={s.id} value={s.id}>
                  {senseTag(s)} · {s.gloss}
                </option>
              ))}
            </select>
          </Field>
          {parent && (
            <Field label="Shift type" required>
              <select className="input" value={shift} onChange={(e) => setShift(e.target.value as ShiftType)}>
                {SHIFT_TYPES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Date as recorded" required hint="Crawls only show the sense existed by then; give an earlier date if you know one.">
            <input className="input" value={dateLabel} maxLength={40} onChange={(e) => setDateLabel(e.target.value)} />
          </Field>
          <Field label="Earliest year" required>
            <input className="input input-year mono" inputMode="numeric" value={dateYear} onChange={(e) => setDateYear(e.target.value.replace(/\D/g, ''))} />
          </Field>
        </div>
      )}

      <Field label="Review note" required={action === 'reject'} hint={action === 'reject' ? 'Why: noise, several senses mixed, a name …' : undefined}>
        <input className="input" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      </Field>

      {review.isError && (
        <p className="field-error" role="alert">
          {review.error.message}
        </p>
      )}
      <div>
        <button className="btn btn-primary" disabled={!ready || review.isPending} onClick={() => review.mutate()}>
          <Check size={14} aria-hidden="true" />
          {action === 'match' ? 'Match to this sense' : action === 'promote' ? 'Add as a new sense' : 'Reject candidate'}
        </button>
      </div>
    </div>
  );
}
