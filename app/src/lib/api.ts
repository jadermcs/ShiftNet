import { get, post, seg } from './http';
import type {
  Attestation,
  CloseSpelling,
  LexiconStats,
  PathStep,
  Sense,
  SenseDetail,
  SenseRef,
  Suggestion,
  Synset,
  SynsetCard,
  WordSummary,
} from './types';

/** Attestations shown on a word page's sense cards (the API returns this many per sense). */
export const TOP_ATTESTATIONS = 3;

export function fetchWords(): Promise<WordSummary[]> {
  return get('words');
}

export function fetchRecent(limit = 10): Promise<Sense[]> {
  return get('recent', { limit });
}

/** All senses of a head word, oldest first, each with its top attestations. Empty when the lemma is not a head word. */
export function fetchWord(lemma: string): Promise<Sense[]> {
  return get(`word/${seg(lemma)}`);
}

/** Every attestation of a sense, most relevant first (distinct works before a work's second quotation). */
export function fetchAttestations(senseId: string): Promise<Attestation[]> {
  return get(`sense/${seg(senseId)}/attestations`);
}

export function fetchSense(id: string): Promise<SenseDetail | null> {
  return get(`sense/${seg(id)}`);
}

/** A synset with every hypernym it sits under, the breadcrumb one (position 0) first. */
export function fetchSynset(id: string): Promise<Synset | null> {
  return get(`synset/${seg(id)}`);
}

/** The synset and its ancestors along the first hypernym, root first. */
export function fetchSynsetPath(id: string): Promise<PathStep[]> {
  return get(`synset/${seg(id)}/path`);
}

export function fetchHyponyms(id: string): Promise<SynsetCard[]> {
  return get(`synset/${seg(id)}/hyponyms`);
}

export function fetchTaxonomyRoots(): Promise<SynsetCard[]> {
  return get('taxonomy/roots');
}

/** Dated senses that belong to a synset, oldest first. */
export function fetchSynsetSenses(id: string): Promise<SenseRef[]> {
  return get(`synset/${seg(id)}/senses`);
}

export function fetchStats(): Promise<LexiconStats> {
  return get('stats');
}

export function fetchChildren(id: string): Promise<SenseRef[]> {
  return get(`sense/${seg(id)}/children`);
}

export function searchLemmas(q: string, max = 8): Promise<Suggestion[]> {
  return get('search', { q, max });
}

export function closeSpellings(q: string, max = 5): Promise<CloseSpelling[]> {
  return get('close-spellings', { q, max });
}

export function resolveLemma(q: string): Promise<CloseSpelling | null> {
  return get('resolve', { q });
}

/** Years of every dated attestation of the given senses, for the dominance chart. */
export async function fetchAttestationYears(senseIds: string[]): Promise<{ sense_id: string; year: number }[]> {
  if (!senseIds.length) return [];
  return post('attestation-years', { ids: senseIds });
}
