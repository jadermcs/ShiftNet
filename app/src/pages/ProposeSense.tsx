import { useDeferredValue, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchWord } from '../lib/api';
import { ChecksFailed, checkSense, compact, submitSense, type Check, type Contribution, type SenseProposal } from '../lib/contributions';
import { CURRENT_YEAR, senseTag } from '../lib/format';
import { POS_ORDER, SHIFT_TYPES, type Pos, type Sense, type ShiftType, type SourceType } from '../lib/types';
import { errorFor, Field } from '../components/Field';
import { useCrumbs } from '../components/Shell';
import { SubmitBar, SubmitResult } from '../components/SubmitBar';
import { EMPTY_USAGE, UsageFields, usagePayload, type UsageInput } from '../components/UsageFields';
import { ValidationBadge } from '../components/ValidationBadge';

const SOURCE_TYPES: SourceType[] = ['dictionary', 'corpus', 'citation'];

interface SenseInput extends Omit<SenseProposal, 'examples' | 'usage'> {
  examples: string; // one per line
}

const EMPTY_SENSE: Omit<SenseInput, 'lemma'> = {
  pos: '',
  gloss: '',
  examples: '',
  date_label: '',
  date_earliest: '',
  shift: '',
  date_source: '',
  source_type: '',
  parents: [],
};

/** Senses of a word, also trying lower case ("Cloud" → cloud). */
async function wordSenses(lemma: string): Promise<Sense[]> {
  const rows = await fetchWord(lemma);
  return rows.length || lemma === lemma.toLowerCase() ? rows : fetchWord(lemma.toLowerCase());
}

export function ProposeSense() {
  const [params] = useSearchParams();
  const initial = params.get('lemma') ?? '';
  useCrumbs([
    { label: 'Contribute', to: '/contribute' },
    ...(initial ? [{ label: initial, to: `/word/${encodeURIComponent(initial)}` }] : []),
    { label: 'Propose a sense' },
  ]);
  return (
    <>
      <div className="card page-head">
        <span className="label">Contribute</span>
        <h1 className="h-page">Propose a sense</h1>
        <p className="muted">
          A sense missing from ShiftNet, for a word already here or a new one: what it means, when it is first recorded and
          which older sense it grew from. Add a dated quotation to support it.
        </p>
      </div>
      <SenseForm key={initial} initialLemma={initial} />
    </>
  );
}

function SenseForm({ initialLemma }: { initialLemma: string }) {
  const qc = useQueryClient();
  const [s, setS] = useState<SenseInput>({ ...EMPTY_SENSE, lemma: initialLemma });
  const [withUsage, setWithUsage] = useState(true);
  const [u, setU] = useState<UsageInput>(EMPTY_USAGE);
  const [otherParent, setOtherParent] = useState('');
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Contribution | null>(null);

  const lemma = useDeferredValue(s.lemma.trim());
  const word = useQuery({ queryKey: ['word-senses', lemma], queryFn: () => wordSenses(lemma), enabled: lemma.length > 0 });
  const set = (patch: Partial<SenseInput>) => setS((x) => ({ ...x, ...patch }));
  const toggleParent = (id: string) =>
    set({ parents: s.parents.includes(id) ? s.parents.filter((p) => p !== id) : [...s.parents, id] });

  const payload = (): SenseProposal => {
    const { examples, ...rest } = s;
    const extra = otherParent.trim();
    return {
      ...compact(rest),
      examples: examples.split('\n').map((e) => e.trim()).filter(Boolean),
      parents: s.shift === 'root' ? [] : extra && !s.parents.includes(extra) ? [...s.parents, extra] : s.parents,
      usage: withUsage ? usagePayload(u) : undefined,
    } as SenseProposal;
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
      const c = await submitSense(payload());
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
          setS({ ...EMPTY_SENSE, lemma: s.lemma });
          setU(EMPTY_USAGE);
        }}
      />
    );

  const existing = word.data ?? [];
  const ck = checks ?? undefined;

  return (
    <form className="card form-card" onSubmit={onSubmit} aria-label="Proposed sense">
      <fieldset className="fieldset">
        <legend className="label">Sense</legend>
        <div className="form-grid">
          <Field
            label="Word"
            required
            error={errorFor(ck, 'lemma')}
            hint={lemma && word.isSuccess ? (existing.length ? `${existing.length} senses in ShiftNet` : 'A new head word') : undefined}
          >
            <input className="input" maxLength={60} value={s.lemma} onChange={(e) => set({ lemma: e.target.value, parents: [] })} autoComplete="off" />
          </Field>
          <Field label="Part of speech" required error={errorFor(ck, 'pos')}>
            <select className="input" value={s.pos} onChange={(e) => set({ pos: e.target.value as Pos })}>
              <option value="">Choose…</option>
              {POS_ORDER.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Gloss" required wide hint="A short definition, like the ones on the word page" error={errorFor(ck, 'gloss_length', 'duplicate_gloss')}>
            <textarea className="input textarea" rows={2} maxLength={300} value={s.gloss} onChange={(e) => set({ gloss: e.target.value })} />
          </Field>
          <Field label="Examples" wide hint="Short made-up phrases, one per line, up to 5" error={errorFor(ck, 'examples')}>
            <textarea className="input textarea" rows={2} value={s.examples} onChange={(e) => set({ examples: e.target.value })} />
          </Field>
          <Field label="Date as recorded" required hint="1965, c. 1300, 16th c., 1990s" error={errorFor(ck, 'date_label')}>
            <input className="input" maxLength={40} value={s.date_label} onChange={(e) => set({ date_label: e.target.value })} />
          </Field>
          <Field label="Earliest year" required hint="Used for sorting: 16th c. → 1500" error={errorFor(ck, 'date_earliest')}>
            <input
              className="input"
              type="number"
              min={600}
              max={CURRENT_YEAR}
              step={1}
              value={s.date_earliest}
              onChange={(e) => set({ date_earliest: e.target.value })}
            />
          </Field>
          <Field label="Date source" required hint="Where the date comes from: a dictionary entry, a corpus search, a citation" error={errorFor(ck, 'date_source')}>
            <input className="input" maxLength={300} value={s.date_source} onChange={(e) => set({ date_source: e.target.value })} />
          </Field>
          <Field label="Source type" required error={errorFor(ck, 'source_type')}>
            <select className="input" value={s.source_type} onChange={(e) => set({ source_type: e.target.value as SourceType })}>
              <option value="">Choose…</option>
              {SOURCE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </fieldset>

      <fieldset className="fieldset">
        <legend className="label">Lineage</legend>
        <div className="form-grid">
          <Field label="Shift type" required error={errorFor(ck, 'shift', 'root_parents')} hint="How it grew from its parent; root if it grew from no other sense">
            <select className="input" value={s.shift} onChange={(e) => set({ shift: e.target.value as ShiftType })}>
              <option value="">Choose…</option>
              <option value="root">root (no parent sense)</option>
              {SHIFT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {s.shift !== 'root' && (
          <div className="stack-8">
            <span className="field-label" id="parents-label">
              Parent senses <span className="muted small">(the first one ticked is the branch it grows from)</span>
            </span>
            {existing.length > 0 ? (
              <ul className="choice-list" aria-labelledby="parents-label">
                {existing.map((x) => {
                  const i = s.parents.indexOf(x.id);
                  return (
                    <li key={x.id}>
                      <label className="choice">
                        <input type="checkbox" checked={i >= 0} onChange={() => toggleParent(x.id)} />
                        <span className="mono small fg2 nowrap">
                          {senseTag(x)} · {x.date_label}
                        </span>
                        <span>{x.gloss}</span>
                        {x.validation !== 'editorial' && <ValidationBadge state={x.validation} compact />}
                        {i === 0 && <span className="chip chip-sm">branch</span>}
                        {i > 0 && <span className="chip chip-sm">merged</span>}
                      </label>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="small muted">{lemma ? 'This word has no senses yet; give a parent from another word below.' : 'Enter the word first.'}</p>
            )}
            <div className="form-grid">
              <Field label="Parent from another word" hint="A sense id, e.g. troll.n.01" error={errorFor(ck, 'parents_exist', 'parents_count')}>
                <input className="input mono" value={otherParent} onChange={(e) => setOtherParent(e.target.value)} autoComplete="off" />
              </Field>
            </div>
          </div>
        )}
      </fieldset>

      <fieldset className="fieldset">
        <legend className="label">Supporting usage</legend>
        <label className="row-gap small fg2">
          <input type="checkbox" checked={withUsage} onChange={(e) => setWithUsage(e.target.checked)} />
          Add a dated quotation showing the sense in use (recommended; without one a moderator reviews the sense)
        </label>
        {withUsage && <UsageFields value={u} onChange={setU} checks={ck} lemma={s.lemma.trim() || undefined} />}
      </fieldset>

      <SubmitBar busy={busy} checks={checks} error={error} onCheck={() => run(async () => setChecks(await checkSense(payload())))} />
    </form>
  );
}
