import { CURRENT_YEAR } from '../lib/format';
import { compact, type Check, type UsageProposal } from '../lib/contributions';
import { errorFor, Field } from './Field';
import { EMPTY_REFERENCE, ReferenceFields } from './ReferenceFields';

export type UsageInput = Omit<UsageProposal, 'sense_id'>;

export const EMPTY_USAGE: UsageInput = { quote: '', year: '', date_label: '', locator: '', source: EMPTY_REFERENCE };

/** Quote, its date and locator, and the reference it comes from. */
export function UsageFields({
  value: u,
  onChange,
  checks,
  lemma,
}: {
  value: UsageInput;
  onChange: (u: UsageInput) => void;
  checks?: Check[];
  lemma?: string;
}) {
  const set = (patch: Partial<UsageInput>) => onChange({ ...u, ...patch });
  return (
    <>
      <div className="form-grid">
        <Field
          label="Quote"
          required
          wide
          hint={`One or two sentences, exactly as printed${lemma ? `, using “${lemma}” in this sense` : ''}`}
          error={errorFor(checks, 'quote_length', 'duplicate_quote')}
        >
          <textarea className="input textarea" rows={4} maxLength={1200} value={u.quote} onChange={(e) => set({ quote: e.target.value })} />
        </Field>
        <Field label="Year of the use" required error={errorFor(checks, 'year')}>
          <input
            className="input"
            type="number"
            min={600}
            max={CURRENT_YEAR}
            step={1}
            value={u.year}
            onChange={(e) => set({ year: e.target.value })}
          />
        </Field>
        <Field label="Date as recorded" hint="When more or less precise than the year: 12 May 1843, c. 1400" error={errorFor(checks, 'label_lengths')}>
          <input className="input" maxLength={40} value={u.date_label ?? ''} onChange={(e) => set({ date_label: e.target.value })} />
        </Field>
        <Field label="Page or locator" hint="p. 12, ch. 3, 01:02:15">
          <input className="input" maxLength={80} value={u.locator ?? ''} onChange={(e) => set({ locator: e.target.value })} />
        </Field>
      </div>
      <ReferenceFields value={u.source} onChange={(source) => set({ source })} checks={checks} />
    </>
  );
}

/** The payload sent to the server: empty fields dropped. */
export const usagePayload = (u: UsageInput): UsageInput => ({ ...compact(u), source: compact(u.source) });
