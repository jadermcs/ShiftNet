export const POS_ORDER = ['noun', 'verb', 'adjective', 'adverb'] as const;
export type Pos = (typeof POS_ORDER)[number];

export const SHIFT_TYPES = [
  'broadening',
  'narrowing',
  'metaphor',
  'metonymy',
  'amelioration',
  'pejoration',
  'other',
] as const;
export type ShiftType = (typeof SHIFT_TYPES)[number] | 'root';

export type SourceType = 'dictionary' | 'corpus' | 'citation';

export const REFERENCE_KINDS = ['book', 'website', 'article', 'journal', 'newspaper', 'dictionary', 'corpus', 'archive', 'other'] as const;
export type ReferenceKind = (typeof REFERENCE_KINDS)[number];

/** How a published row was checked (public.validation_method). */
export type ValidationMethod = 'editorial' | 'automatic' | 'manual';
/** What the interface can show: a published row's method, or a contribution still waiting for review. */
export type ValidationState = ValidationMethod | 'pending';

/** A cited work (public.sources). */
export interface Reference {
  id: string;
  kind: ReferenceKind;
  title: string;
  author: string | null;
  publisher: string | null;
  published_label: string | null;
  published_year: number | null;
  url: string | null;
  identifier: string | null;
  accessed_on: string | null;
}

/** A dated quotation showing a sense in use (public.attestations). */
export interface Attestation {
  id: string;
  sense_id: string;
  quote: string;
  year: number | null;
  date_label: string | null;
  locator: string | null;
  relevance: number;
  validation: ValidationMethod;
  source: Reference;
  /** Display position within the sense, from 1 (public.ranked_attestations). */
  rank: number;
}

export const RELATION_TYPES = ['antonym', 'hypernym', 'hyponym', 'meronym', 'holonym', 'derived'] as const;
export type RelationType = (typeof RELATION_TYPES)[number];

/** Minimal fields needed to label a sense (e.g. a parent from another word). */
export interface SenseRef {
  id: string;
  lemma: string;
  pos: Pos;
  sense_num: number;
  date_label: string;
  date_earliest: number;
  gloss: string;
}

export interface ParentLink {
  position: number;
  source: string | null;
  parent: SenseRef;
}

export interface Sense extends SenseRef {
  examples: string[];
  obsolete_year: number | null;
  obsolete_label: string | null;
  shift: ShiftType;
  source: string;
  source_type: SourceType;
  validation: ValidationMethod;
  branch: number;
  parents: ParentLink[];
  synonyms: { lemma: string; position: number }[];
  /** Only on word pages (fetchWord): the most relevant attestations and the total. */
  top_attestations?: Attestation[];
  attestation_count?: number;
}

export interface Relation {
  type: RelationType;
  target_lemma: string;
  position: number;
}

export interface SenseDetail extends Sense {
  relations: Relation[];
}

export interface WordSummary {
  lemma: string;
  pos: Pos[];
  sense_count: number;
  first_year: number;
}

export interface Suggestion {
  lemma: string;
  kind: 'word' | 'sense';
  sense_id: string | null;
  pos: string;
  meta: string;
}

export interface CloseSpelling {
  lemma: string;
  kind: 'word' | 'sense';
  sense_id: string | null;
}

export interface Period {
  label: string;
  row_offset: number;
}
