import type { Pos, SenseRef } from './types';

/** Branch palette, in registration order within a word. Mirrors --sn-branch-a…h. */
export const BRANCH_COLORS = ['#2ec4a6', '#e8b923', '#e040c8', '#3d9be9', '#f08a3c', '#e5484d', '#8bc34a', '#a07cf0'];
export const BRANCH_LETTERS = 'ABCDEFGH';

export const branchColor = (b: number) => BRANCH_COLORS[((b % 8) + 8) % 8];
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

const ordinal = (n: number) => {
  const t = n % 100;
  if (t >= 11 && t <= 13) return `${n}th`;
  return n + (['th', 'st', 'nd', 'rd'][n % 10] ?? 'th');
};

/** Year separator in the global timeline. Same rules as public.period_label. */
export const periodLabel = (y: number) =>
  y < 1100 ? 'Old English' : y >= 1900 ? `${Math.floor(y / 10) * 10}s` : `${ordinal(Math.floor(y / 100) + 1)} century`;

export const slug = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, '-');

export const index = (n: number, width: number) => String(n).padStart(width, '0');

export const CURRENT_YEAR = new Date().getFullYear();
