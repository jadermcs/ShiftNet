import { CURRENT_YEAR } from '../lib/format';
import { REFERENCE_KINDS, type ReferenceKind } from '../lib/types';
import type { Check, ReferenceInput } from '../lib/contributions';
import { errorFor, Field } from './Field';

const PUBLISHER_LABEL: Partial<Record<ReferenceKind, string>> = {
  website: 'Site name',
  journal: 'Journal',
  newspaper: 'Newspaper',
  article: 'Publication',
  corpus: 'Corpus',
  archive: 'Archive or collection',
};
const IDENTIFIER_LABEL: Partial<Record<ReferenceKind, string>> = {
  book: 'ISBN',
  journal: 'DOI',
  article: 'DOI',
  archive: 'Shelfmark',
  corpus: 'Document id',
};

export const EMPTY_REFERENCE: ReferenceInput = { kind: '', title: '' };

/** The cited work of a usage: kind first, then the fields that kind needs. */
export function ReferenceFields({
  value: r,
  onChange,
  checks,
}: {
  value: ReferenceInput;
  onChange: (r: ReferenceInput) => void;
  checks?: Check[];
}) {
  const set = (patch: Partial<ReferenceInput>) => onChange({ ...r, ...patch });
  const kind = r.kind || undefined;
  const isWeb = r.kind === 'website';

  return (
    <fieldset className="fieldset">
      <legend className="label">Reference</legend>
      <div className="form-grid">
        <Field label="Kind of work" required error={errorFor(checks, 'reference_kind')}>
          <select className="input" value={r.kind} onChange={(e) => set({ kind: e.target.value as ReferenceKind })}>
            <option value="">Choose…</option>
            {REFERENCE_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </Field>
        <Field label={isWeb ? 'Page title' : 'Title'} required error={errorFor(checks, 'reference_title')}>
          <input className="input" maxLength={300} value={r.title} onChange={(e) => set({ title: e.target.value })} />
        </Field>
        <Field label="Author">
          <input className="input" maxLength={200} value={r.author ?? ''} onChange={(e) => set({ author: e.target.value })} />
        </Field>
        <Field label={(kind && PUBLISHER_LABEL[kind]) ?? 'Publisher'}>
          <input className="input" maxLength={200} value={r.publisher ?? ''} onChange={(e) => set({ publisher: e.target.value })} />
        </Field>
        <Field label="Published (as recorded)" hint="e.g. March 1990, c. 1400">
          <input className="input" maxLength={40} value={r.published_label ?? ''} onChange={(e) => set({ published_label: e.target.value })} />
        </Field>
        <Field label="Year published" error={errorFor(checks, 'reference_year')}>
          <input
            className="input"
            type="number"
            min={600}
            max={CURRENT_YEAR}
            step={1}
            value={r.published_year ?? ''}
            onChange={(e) => set({ published_year: e.target.value })}
          />
        </Field>
        <Field
          label="URL"
          required={isWeb}
          hint={isWeb ? undefined : 'A link to the text or a scan lets the reference be checked'}
          error={errorFor(checks, 'url_format', 'website_url')}
          wide
        >
          <input className="input" type="url" inputMode="url" placeholder="https://" value={r.url ?? ''} onChange={(e) => set({ url: e.target.value })} />
        </Field>
        <Field
          label={(kind && IDENTIFIER_LABEL[kind]) ?? 'Identifier'}
          hint="ISBN, DOI, shelfmark …"
          error={errorFor(checks, 'reference_lengths')}
        >
          <input className="input mono" maxLength={100} value={r.identifier ?? ''} onChange={(e) => set({ identifier: e.target.value })} />
        </Field>
        {(isWeb || r.accessed_on) && (
          <Field label="Accessed on" error={errorFor(checks, 'accessed_on_valid')}>
            <input
              className="input"
              type="date"
              max={new Date().toISOString().slice(0, 10)}
              value={r.accessed_on ?? ''}
              onChange={(e) => set({ accessed_on: e.target.value })}
            />
          </Field>
        )}
      </div>
    </fieldset>
  );
}
