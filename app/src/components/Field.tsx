import { cloneElement, useId, type ReactElement, type ReactNode } from 'react';

/**
 * A labelled form control with an optional hint and error. The control (input, select, textarea)
 * gets the id, aria-describedby and aria-invalid.
 */
export function Field({
  label,
  hint,
  error,
  required = false,
  wide = false,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  wide?: boolean;
  children: ReactElement;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const control = cloneElement(children, {
    id,
    required: required || undefined,
    'aria-invalid': error ? true : undefined,
    'aria-describedby': [hintId, errId].filter(Boolean).join(' ') || undefined,
  });
  return (
    <div className={`field${wide ? ' field-wide' : ''}`}>
      <label htmlFor={id} className="field-label">
        {label}
        {required ? <span className="field-req" aria-hidden="true"> *</span> : <span className="muted small"> (optional)</span>}
      </label>
      {control}
      {hint && (
        <span id={hintId} className="field-hint">
          {hint}
        </span>
      )}
      {error && (
        <span id={errId} className="field-error">
          {error}
        </span>
      )}
    </div>
  );
}

/** Error text for a field: the messages of the failed checks with one of these codes. */
export const errorFor = (checks: { code: string; level: string; message: string }[] | undefined, ...codes: string[]) =>
  checks
    ?.filter((c) => c.level === 'error' && codes.includes(c.code))
    .map((c) => c.message)
    .join(' ') || null;
