import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { fetchSense, fetchWord } from '../lib/api';
import { ChecksFailed, checkUsage, submitUsage, type Check, type Contribution } from '../lib/contributions';
import { senseTag } from '../lib/format';
import type { SenseRef, ValidationMethod } from '../lib/types';
import { Field } from '../components/Field';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';
import { SubmitBar, SubmitResult } from '../components/SubmitBar';
import { EMPTY_USAGE, UsageFields, usagePayload, type UsageInput } from '../components/UsageFields';
import { ValidationBadge } from '../components/ValidationBadge';

export function ProposeUsage() {
  const [params, setParams] = useSearchParams();
  const senseId = params.get('sense');
  const sense = useQuery({ queryKey: ['sense', senseId], queryFn: () => fetchSense(senseId!), enabled: !!senseId });
  const s = sense.data;
  useCrumbs([
    { label: 'Contribute', to: '/contribute' },
    ...(s ? [{ label: s.lemma, to: `/word/${encodeURIComponent(s.lemma)}` }, { label: senseTag(s), to: `/sense/${s.id}` }] : []),
    { label: 'Propose a usage' },
  ]);

  return (
    <>
      <div className="card page-head">
        <span className="label">Contribute</span>
        <h1 className="h-page">Propose a usage</h1>
        <p className="muted">
          A usage is a dated quotation showing a sense in use, with the work it comes from. Earlier uses than the date we
          record (antedatings) are especially welcome; a moderator checks those.
        </p>
      </div>
      {!senseId ? (
        <SensePicker onPick={(id) => setParams({ sense: id })} />
      ) : sense.isPending ? (
        <Loading label="Loading sense…" />
      ) : sense.isError ? (
        <ErrorState error={sense.error} retry={() => sense.refetch()} />
      ) : !s ? (
        <>
          <p className="card state" role="alert">
            There is no sense <span className="mono">{senseId}</span>.
          </p>
          <SensePicker onPick={(id) => setParams({ sense: id })} />
        </>
      ) : (
        <>
          <div className="card propose-target">
            <span className="label">Sense</span>
            <div className="row-gap wrap">
              <Link to={`/sense/${s.id}`} className="strong-lg">
                {s.lemma} <span className="mono fg2">{senseTag(s)}</span>
              </Link>
              <span className="mono small muted">registered {s.date_label}</span>
              <ValidationBadge state={s.validation} compact={s.validation === 'editorial'} />
              <button className="link-btn underline small push-right" onClick={() => setParams({})}>
                Choose another sense
              </button>
            </div>
            <div className="gloss">{s.gloss}</div>
          </div>
          <UsageForm key={s.id} senseId={s.id} lemma={s.lemma} />
        </>
      )}

    </>
  );
}

function UsageForm({ senseId, lemma }: { senseId: string; lemma: string }) {
  const qc = useQueryClient();
  const [u, setU] = useState<UsageInput>(EMPTY_USAGE);
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Contribution | null>(null);

  const payload = () => ({ ...usagePayload(u), sense_id: senseId });
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
      const c = await submitUsage(payload());
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
          setU({ ...EMPTY_USAGE, source: u.source });
        }}
      />
    );

  return (
    <form className="card form-card" onSubmit={onSubmit} aria-label="Proposed usage">
      <UsageFields value={u} onChange={setU} checks={checks ?? undefined} lemma={lemma} />
      <SubmitBar busy={busy} checks={checks} error={error} onCheck={() => run(async () => setChecks(await checkUsage(payload())))} />
    </form>
  );
}

/** Find a word, then pick one of its senses. */
export function SensePicker({ onPick, title = 'Which sense does the quote show?' }: { onPick: (id: string) => void; title?: string }) {
  const [q, setQ] = useState('');
  const [lemma, setLemma] = useState('');
  const word = useQuery({ queryKey: ['word', lemma], queryFn: () => fetchWord(lemma), enabled: !!lemma });

  return (
    <section className="card form-card" aria-labelledby="pick-h">
      <h2 id="pick-h" className="form-title">
        {title}
      </h2>
      <form
        className="form-row"
        onSubmit={(e) => {
          e.preventDefault();
          setLemma(q.trim().toLowerCase());
        }}
      >
        <Field label="Word" required>
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
        </Field>
        <button className="btn">
          <Search size={14} aria-hidden="true" />
          Find senses
        </button>
      </form>
      {word.isFetching && <Loading />}
      {word.isError && <ErrorState error={word.error} retry={() => word.refetch()} />}
      {word.data?.length === 0 && (
        <p className="small muted">
          No word “{lemma}” in ShiftNet. You can{' '}
          <Link to={`/contribute/sense?lemma=${encodeURIComponent(lemma)}`} className="inline-link">
            propose it as a new sense
          </Link>
          .
        </p>
      )}
      {word.data && word.data.length > 0 && <SenseChoices senses={word.data} onPick={onPick} />}
    </section>
  );
}

export function SenseChoices({ senses, onPick }: { senses: (SenseRef & { validation?: ValidationMethod })[]; onPick: (id: string) => void }) {
  return (
    <ul className="choice-list">
      {senses.map((x) => (
        <li key={x.id}>
          <button type="button" className="choice" onClick={() => onPick(x.id)}>
            <span className="mono small fg2 nowrap">
              {senseTag(x)} · {x.date_label}
            </span>
            <span>{x.gloss}</span>
            {x.validation && x.validation !== 'editorial' && <ValidationBadge state={x.validation} compact />}
          </button>
        </li>
      ))}
    </ul>
  );
}
