import { BadgeCheck, Bot, BookMarked, Clock, XCircle, type LucideIcon } from 'lucide-react';
import type { ValidationState } from '../lib/types';

/** ValidationState, plus 'rejected' for a contribution a moderator turned down (never part of the lexicon). */
export type BadgeState = ValidationState | 'rejected';

const STATES: Record<BadgeState, { icon: LucideIcon; label: string; title: string }> = {
  editorial: { icon: BookMarked, label: 'Editorial', title: 'Loaded and checked by the ShiftNet team' },
  manual: { icon: BadgeCheck, label: 'Reviewed', title: 'Contributed, then checked by a moderator' },
  automatic: { icon: Bot, label: 'Auto-checked', title: 'Contributed and passed the automatic checks; not yet reviewed by a person' },
  pending: { icon: Clock, label: 'Pending review', title: 'Contributed and waiting for review; not part of the lexicon yet' },
  rejected: { icon: XCircle, label: 'Rejected', title: 'Contributed and turned down by a moderator; not part of the lexicon' },
};

/** How a row was validated: editorial data, a reviewed or auto-checked contribution, or a pending or rejected one. */
export function ValidationBadge({ state, compact = false }: { state: BadgeState; compact?: boolean }) {
  const { icon: Icon, label, title } = STATES[state];
  return (
    <span className={`validation validation-${state}`} title={title} aria-label={`${label}: ${title}`}>
      <Icon size={12} aria-hidden="true" />
      {!compact && label}
    </span>
  );
}
