import { useEffect, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { useQuery } from '@tanstack/react-query';
import { supabase } from './supabase';
import type { Pos, ReferenceKind, ShiftType, SourceType, ValidationMethod } from './types';

// Community contributions (public.contributions). Submissions go through RPCs that run the
// automatic checks server side; see supabase/migrations/20261022140000_contributions.sql.

export type ContributionKind = 'usage' | 'sense' | 'relation';
export type ContributionStatus = 'pending' | 'accepted' | 'rejected';

/** One automatic check. error blocks the submission, review sends it to a moderator. */
export type CheckLevel = 'error' | 'review' | 'note' | 'pass';
export interface Check {
  code: string;
  level: CheckLevel;
  message: string;
}

/** A cited work as entered in a form (public.sources without id). */
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

/** WordNet relations a contributor can propose. Synonyms join the sense's synset; the rest go to public.relations. */
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

/** A relation proposed by the LexSPLADE encoder (public.relation_suggestions), shown as a starting point. */
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

/** Thrown when the automatic checks refuse a submission; carries the failed checks. */
export class ChecksFailed extends Error {
  constructor(message: string, readonly checks: Check[]) {
    super(message);
  }
}

type RpcError = { message: string; details?: string | null; hint?: string | null } | null;

function unwrap<T>({ data, error }: { data: unknown; error: RpcError }): T {
  if (error) {
    let checks: Check[] = [];
    try {
      checks = error.details ? (JSON.parse(error.details) as Check[]) : [];
    } catch {
      // details is plain text for other errors
    }
    if (Array.isArray(checks) && checks.length) throw new ChecksFailed(error.message, checks);
    throw new Error(error.message);
  }
  return data as T;
}

// ---------- Auth ----------

/** The current session, kept in step with sign-in and sign-out. undefined while loading. */
export function useSession(): Session | null | undefined {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);
  return session;
}

/** Email a magic link and a 6-digit code. New addresses get an account. */
export async function sendSignInEmail(email: string, redirectPath: string) {
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: window.location.origin + redirectPath, shouldCreateUser: true },
  });
  if (error) throw new Error(error.message);
}

/** Redirect to GitHub; the PKCE code in the return URL is exchanged by the client (detectSessionInUrl). */
export async function signInWithGitHub(redirectPath: string) {
  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'github',
    options: { redirectTo: window.location.origin + redirectPath },
  });
  if (error) throw new Error(error.message);
}

export async function verifySignInCode(email: string, token: string) {
  const { error } = await supabase.auth.verifyOtp({ email, token, type: 'email' });
  if (error) throw new Error(error.message);
}

export async function signOut() {
  const { error } = await supabase.auth.signOut();
  if (error) throw new Error(error.message);
}

export async function fetchIsModerator(): Promise<boolean> {
  return unwrap(await supabase.rpc('is_moderator'));
}

/** Whether the signed-in user may review. Decided server side (public.moderators). */
export function useIsModerator(session: Session | null | undefined) {
  const uid = session?.user.id;
  return useQuery({ queryKey: ['is-moderator', uid], queryFn: fetchIsModerator, enabled: !!uid, staleTime: 5 * 60_000 });
}

// ---------- Submitting ----------

export async function checkUsage(p: UsageProposal): Promise<Check[]> {
  return unwrap(await supabase.rpc('check_usage', { p }));
}

export async function submitUsage(p: UsageProposal): Promise<Contribution> {
  return unwrap(await supabase.rpc('submit_usage', { p }));
}

export async function checkSense(p: SenseProposal): Promise<Check[]> {
  return unwrap(await supabase.rpc('check_sense', { p }));
}

export async function submitSense(p: SenseProposal): Promise<Contribution> {
  return unwrap(await supabase.rpc('submit_sense', { p }));
}

export async function checkRelation(p: RelationProposal): Promise<Check[]> {
  return unwrap(await supabase.rpc('check_relation', { p }));
}

export async function submitRelation(p: RelationProposal): Promise<Contribution> {
  return unwrap(await supabase.rpc('submit_relation', { p }));
}

/** The encoder's suggestions for a sense, strongest first (signed-in users only). */
export async function fetchRelationSuggestions(senseId: string): Promise<RelationSuggestion[]> {
  return unwrap(
    await supabase.from('relation_suggestions').select('*').eq('sense_id', senseId).order('score', { ascending: false }).limit(60),
  );
}

// ---------- Reading ----------
// RLS returns a contributor's own rows, or every row for a moderator.

export async function fetchMyContributions(uid: string): Promise<Contribution[]> {
  return unwrap(
    await supabase.from('contributions').select('*').eq('contributor_id', uid).order('created_at', { ascending: false }).limit(200),
  );
}

/** Pending usages proposed for a sense that this viewer may see (their own; all for a moderator). */
export async function fetchPendingForSense(senseId: string): Promise<Contribution[]> {
  return unwrap(
    await supabase
      .from('contributions')
      .select('*')
      .eq('sense_id', senseId)
      .eq('kind', 'usage')
      .eq('status', 'pending')
      .order('created_at'),
  );
}

export type QueueFilter = 'pending' | 'unconfirmed' | 'decided';

export async function fetchQueue(filter: QueueFilter): Promise<Contribution[]> {
  let q = supabase.from('contributions').select('*');
  if (filter === 'pending') q = q.eq('status', 'pending').order('created_at');
  else if (filter === 'unconfirmed')
    q = q.eq('status', 'accepted').eq('validation', 'automatic').order('decided_at', { ascending: false });
  else q = q.not('reviewer_id', 'is', null).order('decided_at', { ascending: false });
  return unwrap(await q.limit(100));
}

export type ReviewDecision = 'accept' | 'reject';

/** Accept or reject a pending contribution, or confirm / withdraw an auto-accepted one. */
export async function reviewContribution(id: string, decision: ReviewDecision, note: string): Promise<Contribution> {
  return unwrap(await supabase.rpc('review_contribution', { p_id: id, p_decision: decision, p_note: note || null }));
}

// ---------- Form helpers ----------

/** Drop empty strings so the server sees missing fields as missing. */
export function compact<T extends object>(o: T): T {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== '' && v != null)) as T;
}

export const isSenseProposal = (c: Contribution): c is Contribution & { payload: SenseProposal } => c.kind === 'sense';
export const isRelationProposal = (c: Contribution): c is Contribution & { payload: RelationProposal } => c.kind === 'relation';
