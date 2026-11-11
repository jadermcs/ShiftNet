import { get, post, seg } from './http';
import type { Pos, ShiftType } from './types';

// Sense discovery (backend: discovery_runs, sense_candidates, corpus_usages). Each candidate is a
// cluster of a word's usages from the fineweb-edu web corpus. It joins the lexicon only once
// reviewed: matched to an existing sense, promoted to a new one, or rejected.

export type CandidateStatus = 'pending' | 'matched' | 'promoted' | 'rejected';

export interface DiscoveredWord {
  lemma: string;
  /** Frequency rank in fineweb-edu (1 = most frequent), from the bulk import order. */
  rank: number;
  /** Usages clustered over all runs of the word. */
  usages: number;
  candidates: number;
  pending: number;
  first_seen: string | null;
  last_seen: string | null;
  /** Already a head word of the lexicon. */
  in_lexicon: boolean;
}

export interface DiscoveredWords {
  total_words: number;
  pending_words: number;
  /** Words matching the filters, of which `words` is one page. */
  matches: number;
  words: DiscoveredWord[];
}

export interface CorpusUsage {
  id: string;
  context: string;
  target_start: number;
  target_end: number;
  url: string | null;
  crawled_on: string | null;
  dump: string | null;
  /** Cosine similarity to the cluster's centroid: higher is more typical. */
  similarity: number | null;
}

export interface Candidate {
  id: string;
  run_id: string;
  cluster: number;
  size: number;
  status: CandidateStatus;
  /** The strongest dimensions of the cluster's centroid. */
  terms: { term: string; weight: number }[];
  first_seen: string | null;
  last_seen: string | null;
  /** Usages per crawl year. */
  year_counts: Record<string, number>;
  nearest_sense_id: string | null;
  nearest_score: number | null;
  nearest_gloss: string | null;
  nearest_pos: Pos | null;
  nearest_sense_num: number | null;
  /** The sense matched or created on review. */
  sense_id: string | null;
  review_note: string | null;
  decided_at: string | null;
  typical_usages: CorpusUsage[];
  borderline_usages: CorpusUsage[];
}

export interface DiscoveryRun {
  id: string;
  lemma: string;
  forms: string[];
  corpus: string;
  dumps: string[];
  model: string;
  usage_count: number;
  noise_count: number;
  started_at: string;
  bulk_tag: string | null;
}

export interface DiscoveryWord {
  lemma: string;
  runs: DiscoveryRun[];
  candidates: Candidate[];
}

export type WordFilter = 'pending' | 'all';
export type WordSort = 'frequent' | 'alpha' | 'candidates';

export const PAGE_SIZE = 100;

export function fetchDiscoveredWords(q: string, status: WordFilter, sort: WordSort, page: number): Promise<DiscoveredWords> {
  return get('discovery/words', { q, status, sort, offset: page * PAGE_SIZE, limit: PAGE_SIZE });
}

export function fetchDiscoveryWord(lemma: string): Promise<DiscoveryWord | null> {
  return get(`discovery/word/${seg(lemma)}`);
}

export interface CandidateRef {
  id: string;
  status: CandidateStatus;
  sense_id: string | null;
}

/** The cluster is an existing sense; its most typical usages are quoted as attestations of it. */
export function matchCandidate(id: string, p: { sense_id?: string; attestations?: number; note?: string }): Promise<CandidateRef> {
  return post(`discovery/candidates/${seg(id)}/match`, p);
}

export interface PromoteInput {
  pos: Pos;
  gloss: string;
  parent_ids: string[];
  shift?: ShiftType;
  date_label?: string;
  date_earliest?: number;
  note?: string;
}

/** The cluster is a new sense of its word. */
export function promoteCandidate(id: string, p: PromoteInput): Promise<CandidateRef> {
  return post(`discovery/candidates/${seg(id)}/promote`, p);
}

export function rejectCandidate(id: string, note: string): Promise<CandidateRef> {
  return post(`discovery/candidates/${seg(id)}/reject`, { note });
}
