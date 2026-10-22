import { AlertCircle, CheckCircle2, Eye, Info, type LucideIcon } from 'lucide-react';
import type { Check, CheckLevel } from '../lib/contributions';

const LEVELS: Record<CheckLevel, { icon: LucideIcon; label: string }> = {
  error: { icon: AlertCircle, label: 'Must be fixed' },
  review: { icon: Eye, label: 'For a moderator' },
  note: { icon: Info, label: 'Note' },
  pass: { icon: CheckCircle2, label: 'Passed' },
};
const ORDER: CheckLevel[] = ['error', 'review', 'note', 'pass'];

/** Results of the automatic checks, most serious first. Passed checks fold away unless showPassed. */
export function ChecksList({ checks, showPassed = false }: { checks: Check[]; showPassed?: boolean }) {
  const sorted = [...checks].sort((a, b) => ORDER.indexOf(a.level) - ORDER.indexOf(b.level));
  const flagged = sorted.filter((c) => c.level !== 'pass');
  const passed = sorted.filter((c) => c.level === 'pass');
  const item = (c: Check) => {
    const { icon: Icon, label } = LEVELS[c.level];
    return (
      <li key={c.code + c.message} className={`check check-${c.level}`}>
        <Icon size={14} aria-hidden="true" />
        <span className="sr-only">{label}: </span>
        <span>{c.message}</span>
      </li>
    );
  };
  return (
    <div className="stack-4">
      {flagged.length > 0 && <ul className="checks">{flagged.map(item)}</ul>}
      {passed.length > 0 &&
        (showPassed || flagged.length === 0 ? (
          <ul className="checks">{passed.map(item)}</ul>
        ) : (
          <details className="checks-more">
            <summary className="small muted">{passed.length} checks passed</summary>
            <ul className="checks">{passed.map(item)}</ul>
          </details>
        ))}
      {checks.length === 0 && <span className="small muted">No checks recorded.</span>}
    </div>
  );
}

/** One-line outcome of a set of checks, for buttons and summaries. */
export function checksOutcome(checks: Check[]) {
  if (checks.some((c) => c.level === 'error')) return 'error';
  if (checks.some((c) => c.level === 'review')) return 'review';
  return 'ok';
}
