import type { Pos, SenseRef } from './types';

export const BRANCH_LETTERS = 'ABCDEFGH';

/** Branch palette, in registration order within a word: --sn-branch-a…h, so it follows the theme. */
export const branchColor = (b: number) => `var(--sn-branch-${BRANCH_LETTERS[((b % 8) + 8) % 8].toLowerCase()})`;
export const branchLetter = (b: number) => BRANCH_LETTERS[((b % 8) + 8) % 8];

const POS_ABBR: Record<Pos, string> = { noun: 'n.', verb: 'v.', adjective: 'adj.', adverb: 'adv.' };

/** "n. 2", "adj. 3" */
export const senseTag = (s: Pick<SenseRef, 'pos' | 'sense_num'>) => `${POS_ABBR[s.pos]} ${s.sense_num}`;

/** Label a sense relative to the word being read: "n. 1", or "troll v. 2" when it belongs to another word. */
export const senseLabel = (s: SenseRef, currentLemma?: string) =>
  (s.lemma !== currentLemma ? `${s.lemma} ` : '') + senseTag(s);

export const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Case- and accent-insensitive key, same as public.normalize_lemma. */
export const normalize = (s: string) =>
  s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

export const index = (n: number, width: number) => String(n).padStart(width, '0');

export const CURRENT_YEAR = new Date().getFullYear();
