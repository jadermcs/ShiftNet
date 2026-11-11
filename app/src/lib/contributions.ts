import { get, post, seg, type Check } from './http';
import type { Pos, ReferenceKind, ShiftType, SourceType, ValidationMethod } from './types';

export { ChecksFailed, type Check, type CheckLevel } from './http';

// Contributions. Submissions go to the local API, which runs the automatic checks
// (backend/src/shiftnet_backend/contributions.py). There is one local user, who also reviews.

export type ContributionKind = 'usage' | 'sense' | 'relation';
export type ContributionStatus = 'pending' | 'accepted' | 'rejected';

/** A cited work as entered in a form (a source without id). */
export interface ReferenceInput {
  kind: ReferenceKind | '';
  title: string;
  author?: string;
  publisher?: string;
  published_label?: string;
  published_year?: number | string;
  url?: string;
  identifier?: string;
  accessed_on?: string;
}

/** A quotation with its reference. sense_id is omitted for the supporting usage of a proposed sense. */
export interface UsageProposal {
  sense_id?: string;
  quote: string;
  year: number | string;
  date_label?: string;
  locator?: string;
  source: ReferenceInput;
}

export interface SenseProposal {
  lemma: string;
  pos: Pos | '';
  gloss: string;
  examples: string[];
  date_label: string;
  date_earliest: number | string;
  shift: ShiftType | '';
  date_source: string;
  source_type: SourceType | '';
  parents: string[];
  usage?: Omit<UsageProposal, 'sense_id'>;
}

/** WordNet relations a contributor can propose. Synonyms join the sense's synset; the rest are relations. */
export const RELATION_KINDS = ['hypernym', 'hyponym', 'synonym', 'meronym', 'holonym', 'antonym', 'derived'] as const;
export type RelationKind = (typeof RELATION_KINDS)[number];

export const RELATION_LABELS: Record<RelationKind, { name: string; hint: string }> = {
  hypernym: { name: 'Hypernym', hint: 'a broader term (mouse → animal)' },
  hyponym: { name: 'Hyponym', hint: 'a narrower term (mouse → dormouse)' },
  synonym: { name: 'Synonym', hint: 'a word with the same meaning in this sense (shiner → black eye)' },
  meronym: { name: 'Meronym', hint: 'a part of it (mouse → tail)' },
  holonym: { name: 'Holonym', hint: 'the whole it is part of (mouse, the device → computer)' },
  antonym: { name: 'Antonym', hint: 'its opposite (nice → nasty)' },
  derived: { name: 'Derived form', hint: 'a word built from it (cloud → cloudy)' },
};

/** A proposed relation from a sense to a word, optionally pinned to one of the word's senses or a taxonomy synset. */
export interface RelationProposal {
  sense_id: string;
  type: RelationKind | '';
  target_lemma: string;
  target_sense_id?: string;
  target_synset_id?: string;
  note?: string;
}

/** A relation proposed by the LexSPLADE encoder, shown as a starting point. */
export interface RelationSuggestion {
  id: string;
  sense_id: string;
  type: Exclude<RelationKind, 'antonym' | 'derived'>;
  target_lemma: string;
  target_sense_id: string | null;
  target_synset_id: string | null;
  score: number;
  evidence: Record<string, unknown>;
}

export interface Contribution {
  id: string;
  contributor_id: string;
  kind: ContributionKind;
  status: ContributionStatus;
  lemma: string;
  sense_id: string | null;
  attestation_id: string | null;
  payload: UsageProposal | SenseProposal | RelationProposal;
  /** For a published relation: what was written, so it can be withdrawn. */
  published?: { table: string; synset_edge?: { child: string; parent: string } } | null;
  checks: Check[];
  validation: Exclude<ValidationMethod, 'editorial'> | null;
  reviewer_id: string | null;
  review_note: string | null;
  decided_at: string | null;
  created_at: string;
}

/** What the badge shows for a contribution. */
export const contributionState = (c: Pick<Contribution, 'status' | 'validation'>) =>
  c.status === 'accepted' ? (c.validation ?? 'automatic') : c.status;

// ---------- Submitting ----------

export function checkUsage(p: UsageProposal): Promise<Check[]> {
  return post('contributions/check/usage', p);
}

export function submitUsage(p: UsageProposal): Promise<Contribution> {
  return post('contributions/usage', p);
}

export function checkSense(p: SenseProposal): Promise<Check[]> {
  return post('contributions/check/sense', p);
}

export function submitSense(p: SenseProposal): Promise<Contribution> {
  return post('contributions/sense', p);
}

export function checkRelation(p: RelationProposal): Promise<Check[]> {
  return post('contributions/check/relation', p);
}

export function submitRelation(p: RelationProposal): Promise<Contribution> {
  return post('contributions/relation', p);
}

/** The encoder's suggestions for a sense, strongest first. */
export function fetchRelationSuggestions(senseId: string): Promise<RelationSuggestion[]> {
  return get(`sense/${seg(senseId)}/relation-suggestions`);
}

// ---------- Reading ----------

/** Every contribution, newest first (there is one local contributor). */
export function fetchMyContributions(): Promise<Contribution[]> {
  return get('contributions');
}

/** Usages proposed for a sense and waiting for review. */
export function fetchPendingForSense(senseId: string): Promise<Contribution[]> {
  return get(`sense/${seg(senseId)}/pending-usages`);
}

export type QueueFilter = 'pending' | 'unconfirmed' | 'decided';

export function fetchQueue(filter: QueueFilter): Promise<Contribution[]> {
  return get(`contributions/queue/${filter}`);
}

export type ReviewDecision = 'accept' | 'reject';

/** Accept or reject a pending contribution, or confirm / withdraw an auto-accepted one. */
export function reviewContribution(id: string, decision: ReviewDecision, note: string): Promise<Contribution> {
  return post(`contributions/${seg(id)}/review`, { decision, note: note || null });
}

// ---------- Form helpers ----------

/** Drop empty strings so the server sees missing fields as missing. */
export function compact<T extends object>(o: T): T {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== '' && v != null)) as T;
}

export const isSenseProposal = (c: Contribution): c is Contribution & { payload: SenseProposal } => c.kind === 'sense';
export const isRelationProposal = (c: Contribution): c is Contribution & { payload: RelationProposal } => c.kind === 'relation';
