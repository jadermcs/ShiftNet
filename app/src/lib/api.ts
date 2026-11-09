import { supabase } from './supabase';
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

const REF = 'id, lemma, pos, sense_num, date_label, date_earliest, gloss';

const SENSE = `${REF}, examples, obsolete_year, obsolete_label, shift, source, source_type, validation, branch,
  parents:sense_parents!sense_parents_sense_id_fkey(position, source, parent:senses!sense_parents_parent_id_fkey(${REF})),
  synonyms:sense_lemmas(lemma, position)`;

// ranked_attestations inlines the cited work as `source` and orders each sense's quotations by `rank`.
const ATTESTATION = 'id, sense_id, quote, year, date_label, locator, relevance, validation, source, rank, total';

/** Attestations shown on a word page's sense cards. */
export const TOP_ATTESTATIONS = 3;

function unwrap<T>({ data, error }: { data: unknown; error: { message: string } | null }): T {
  if (error) throw new Error(error.message);
  return data as T;
}

function tidy<T extends Sense>(s: T): T {
  s.parents.sort((a, b) => a.position - b.position);
  s.synonyms.sort((a, b) => a.position - b.position);
  return s;
}

export async function fetchWords(): Promise<WordSummary[]> {
  return unwrap(await supabase.from('words').select('*').order('lemma').limit(500));
}

export async function fetchRecent(limit = 10): Promise<Sense[]> {
  const rows = unwrap<Sense[]>(
    await supabase.from('senses').select(SENSE).order('date_earliest', { ascending: false }).order('id').limit(limit),
  );
  return rows.map(tidy);
}

/** All senses of a head word, oldest first, each with its top attestations. Empty when the lemma is not a head word. */
export async function fetchWord(lemma: string): Promise<Sense[]> {
  const rows = unwrap<Sense[]>(
    await supabase.from('senses').select(SENSE).eq('lemma', lemma).order('date_earliest').order('id'),
  );
  if (!rows.length) return rows;
  const top = unwrap<(Attestation & { total: number })[]>(
    await supabase
      .from('ranked_attestations')
      .select(ATTESTATION)
      .in('sense_id', rows.map((r) => r.id))
      .lte('rank', TOP_ATTESTATIONS)
      .order('rank'),
  );
  return rows.map((r) => {
    const mine = top.filter((a) => a.sense_id === r.id);
    return tidy({ ...r, top_attestations: mine, attestation_count: mine[0]?.total ?? 0 });
  });
}

/** Every attestation of a sense, most relevant first (distinct works before a work's second quotation). */
export async function fetchAttestations(senseId: string): Promise<Attestation[]> {
  return unwrap(
    await supabase.from('ranked_attestations').select(ATTESTATION).eq('sense_id', senseId).order('rank'),
  );
}

export async function fetchSense(id: string): Promise<SenseDetail | null> {
  const row = unwrap<SenseDetail | null>(
    await supabase.from('senses').select(`${SENSE}, synset_id, relations(type, target_lemma, position)`).eq('id', id).maybeSingle(),
  );
  if (row) row.relations.sort((a, b) => a.position - b.position);
  return row && tidy(row);
}

const SYNSET = 'id, pos, lemmas, gloss';

/** A synset with every hypernym it sits under, the breadcrumb one (position 0) first. */
export async function fetchSynset(id: string): Promise<Synset | null> {
  const row = unwrap<Synset | null>(
    await supabase
      .from('synsets')
      .select(`${SYNSET}, hypernyms:synset_hypernyms!synset_hypernyms_synset_id_fkey(position, hypernym:synsets!synset_hypernyms_hypernym_id_fkey(${SYNSET}))`)
      .eq('id', id)
      .maybeSingle(),
  );
  row?.hypernyms.sort((a, b) => a.position - b.position);
  return row;
}

/** The synset and its ancestors along the first hypernym, root first. */
export async function fetchSynsetPath(id: string): Promise<PathStep[]> {
  return unwrap(await supabase.rpc('synset_path', { target: id }));
}

export async function fetchHyponyms(id: string): Promise<SynsetCard[]> {
  return unwrap(await supabase.rpc('synset_hyponyms', { target: id }));
}

export async function fetchTaxonomyRoots(): Promise<SynsetCard[]> {
  return unwrap(await supabase.rpc('synset_roots'));
}

/** Dated senses that belong to a synset, oldest first. */
export async function fetchSynsetSenses(id: string): Promise<SenseRef[]> {
  return unwrap(await supabase.from('senses').select(REF).eq('synset_id', id).order('date_earliest').order('id'));
}

export async function fetchStats(): Promise<LexiconStats> {
  const [overview, periods, shifts, transitions] = await Promise.all([
    supabase.rpc('stats_overview').single(),
    supabase.rpc('stats_periods'),
    supabase.rpc('stats_shifts'),
    supabase.rpc('stats_pos_transitions'),
  ]);
  return {
    overview: unwrap(overview),
    periods: unwrap(periods),
    shifts: unwrap(shifts),
    transitions: unwrap(transitions),
  };
}

export async function fetchChildren(id: string): Promise<SenseRef[]> {
  const rows = unwrap<{ child: SenseRef }[]>(
    await supabase
      .from('sense_parents')
      .select(`child:senses!sense_parents_sense_id_fkey(${REF})`)
      .eq('parent_id', id),
  );
  return rows.map((r) => r.child).sort((a, b) => a.date_earliest - b.date_earliest || a.id.localeCompare(b.id));
}

export async function searchLemmas(q: string, max = 8): Promise<Suggestion[]> {
  return unwrap(await supabase.rpc('search_lemmas', { q, max_results: max }));
}

export async function closeSpellings(q: string, max = 5): Promise<CloseSpelling[]> {
  return unwrap(await supabase.rpc('close_spellings', { q, max_results: max }));
}

export async function resolveLemma(q: string): Promise<CloseSpelling | null> {
  const rows = unwrap<CloseSpelling[]>(await supabase.rpc('resolve_lemma', { q }));
  return rows[0] ?? null;
}

/** Years of every dated attestation of the given senses, for the dominance chart. */
export async function fetchAttestationYears(senseIds: string[]): Promise<{ sense_id: string; year: number }[]> {
  if (!senseIds.length) return [];
  return unwrap(
    await supabase.from('attestations').select('sense_id, year').in('sense_id', senseIds).not('year', 'is', null),
  );
}
