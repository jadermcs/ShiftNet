-- WordNet relations through the contribution flow: anyone signed in can propose a synonym, hypernym,
-- hyponym, meronym, holonym, antonym or derived form for a sense, from the Contribute page.
--
-- The backend (backend/, `shiftnet relations suggest`) proposes relations with the LexSPLADE encoder
-- and stores them in relation_suggestions. The form shows them as one-click starting points, and the
-- automatic checks use them as evidence: a relation the model supports, to a word already in ShiftNet,
-- from a trusted contributor, is published at once (validation 'automatic'); anything else waits for a
-- moderator. Synonyms, antonyms and derived forms always wait: the model cannot tell a synonym from a
-- sister term (mouse → rat) and does not propose the other two.
--
-- Publishing writes public.relations (public.sense_lemmas for a synonym). A hypernym or hyponym that
-- names a target sense or synset also adds the edge to the taxonomy, unless the parent is already an
-- ancestor there (mouse is under rodent, so "mouse → animal" adds no edge).
--
-- private.publish and public.review_contribution are wrapped rather than rewritten: the originals
-- become *_base and still handle usages and senses.

alter type public.contribution_kind add value if not exists 'relation';

-- What a published contribution wrote, so it can be withdrawn (relations have no id of their own).
alter table public.contributions add column if not exists published jsonb;

-- ---------- Model suggestions ----------

create table public.relation_suggestions (
  id uuid primary key default gen_random_uuid(),
  sense_id text not null references public.senses (id) on delete cascade,
  type text not null,
  target_lemma text not null,
  target_sense_id text references public.senses (id) on delete set null, -- best-fitting sense of the target in ShiftNet
  target_synset_id text references public.synsets (id) on delete set null, -- or synset of the taxonomy without a dated sense
  target_score real,
  score real not null,                        -- 0–1; the checks treat 0.6 or more as support
  evidence jsonb not null default '{}',       -- how it was found: method, slot weight, substitution similarity …
  model text not null,
  created_at timestamptz not null default now(),
  constraint relation_suggestions_type check (type in ('synonym', 'hypernym', 'hyponym', 'meronym', 'holonym')),
  constraint relation_suggestions_target_not_blank check (length(trim(target_lemma)) > 0),
  constraint relation_suggestions_score_range check (score between 0 and 1)
);

create unique index relation_suggestions_key on public.relation_suggestions (sense_id, type, public.normalize_lemma(target_lemma));
create index relation_suggestions_rank_idx on public.relation_suggestions (sense_id, score desc);
create index relation_suggestions_target_idx on public.relation_suggestions (target_sense_id);

-- ---------- Normalising and checking a proposal ----------

-- {sense_id, type, target_lemma, target_sense_id?, target_synset_id?, note?}
create function private.clean_relation(p jsonb)
returns jsonb
language sql
immutable
set search_path = ''
as $$
  select jsonb_strip_nulls(jsonb_build_object(
    'sense_id', private.clean(p ->> 'sense_id'),
    'type', lower(private.clean(p ->> 'type')),
    'target_lemma', private.clean(p ->> 'target_lemma'),
    'target_sense_id', private.clean(p ->> 'target_sense_id'),
    'target_synset_id', case when private.clean(p ->> 'target_sense_id') is null then private.clean(p ->> 'target_synset_id') end,
    'note', private.clean(p ->> 'note')
  ))
$$;

-- The taxonomy edge a hypernym / hyponym proposal implies: {child, parent} synsets, or null when
-- either side is not placed in the taxonomy. The target is a sense's synset, or a synset named directly.
create function private.relation_edge(p jsonb)
returns jsonb
language sql
stable
set search_path = ''
as $$
  select case
    when e.child is null or e.parent is null then null
    else jsonb_build_object('child', e.child, 'parent', e.parent)
  end
  from (
    select
      case p ->> 'type' when 'hypernym' then s.synset_id else coalesce(t.synset_id, p ->> 'target_synset_id') end as child,
      case p ->> 'type' when 'hypernym' then coalesce(t.synset_id, p ->> 'target_synset_id') else s.synset_id end as parent
    from public.senses s
    left join public.senses t on t.id = p ->> 'target_sense_id'
    where s.id = p ->> 'sense_id' and p ->> 'type' in ('hypernym', 'hyponym')
  ) e
$$;

-- Is `ancestor` on some hypernym path above `child` (or the same synset)?
create function private.synset_above(child text, ancestor text)
returns boolean
language sql
stable
set search_path = ''
as $$
  with recursive up as (
    select child as id, array[child] as seen
    union all
    select h.hypernym_id, up.seen || h.hypernym_id
    from up join public.synset_hypernyms h on h.synset_id = up.id
    where h.hypernym_id <> all (up.seen) and cardinality(up.seen) < 50
  )
  select exists (select 1 from up where id = ancestor)
$$;

-- Everything checked for a proposed relation. uid null (moderator re-check) skips the limits and the trust rule.
create function private.relation_report(p jsonb, uid uuid, p_exclude uuid)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  s public.senses;
  ts public.senses;
  ty text := p ->> 'type';
  t text := p ->> 'target_lemma';
  edge jsonb := private.relation_edge(p);
  sg record;
  accepted integer;
  rejected integer;
  c jsonb := '[]';
begin
  select * into s from public.senses where id = p ->> 'sense_id';
  if not found then
    return private.rule('sense_exists', false, 'error', null, 'Choose an existing sense');
  end if;
  if uid is not null then
    c := c || private.rate_checks(uid);
  end if;

  c := c || private.rule('relation_type',
    ty in ('synonym', 'hypernym', 'hyponym', 'meronym', 'holonym', 'antonym', 'derived'), 'error', null,
    'Choose a relation: synonym, hypernym, hyponym, meronym, holonym, antonym or derived form');
  c := c || private.rule('target_given', t is not null, 'error', null, 'Give the related word');

  if t is not null then
    c := c || private.rule('target_form', length(t) <= 60 and t ~ '^[[:alpha:]][[:alpha:][:digit:] ''’.-]*$', 'error', null,
      'The related word: letters, spaces, hyphens and apostrophes, at most 60 characters');
    c := c || private.rule('not_self', public.normalize_lemma(t) <> public.normalize_lemma(s.lemma), 'error', null,
      'A word cannot be related to itself');
    c := c || private.rule('not_duplicate',
      not exists (
        select 1 from public.relations r
        where r.sense_id = s.id and r.type::text = ty and public.normalize_lemma(r.target_lemma) = public.normalize_lemma(t)
      ) and not (
        ty = 'synonym' and exists (
          select 1 from public.sense_lemmas l where l.sense_id = s.id and public.normalize_lemma(l.lemma) = public.normalize_lemma(t)
        )
      ) and not exists (
        select 1 from public.contributions k
        where k.kind::text = 'relation' and k.status = 'pending' and k.id is distinct from p_exclude
          and k.sense_id = s.id and k.payload ->> 'type' = ty
          and public.normalize_lemma(k.payload ->> 'target_lemma') = public.normalize_lemma(t)
      ),
      'error', null, 'This relation is already recorded, or already proposed, for this sense');
    c := c || private.rule('known_word',
      exists (select 1 from public.senses x where public.normalize_lemma(x.lemma) = public.normalize_lemma(t))
        or exists (select 1 from public.sense_lemmas l where public.normalize_lemma(l.lemma) = public.normalize_lemma(t))
        or exists (select 1 from public.synsets y, unnest(y.lemmas) m where public.normalize_lemma(m) = public.normalize_lemma(t)),
      'review', format('“%s” is in ShiftNet', t), format('“%s” is not in ShiftNet yet; a moderator will check it', t));
  end if;

  if p ? 'target_sense_id' then
    select * into ts from public.senses where id = p ->> 'target_sense_id';
    c := c || private.rule('target_sense',
      found and (public.normalize_lemma(ts.lemma) = public.normalize_lemma(t)
        or exists (select 1 from public.sense_lemmas l where l.sense_id = ts.id and public.normalize_lemma(l.lemma) = public.normalize_lemma(t))),
      'error', null, 'The target sense must be a sense of the related word');
    if found and ty in ('synonym', 'antonym', 'hypernym', 'hyponym') then
      c := c || private.rule('same_pos', ts.pos = s.pos, 'review', null,
        format('%s is a %s and %s a %s; a moderator will check the relation', s.id, s.pos, ts.id, ts.pos));
    end if;
  elsif p ? 'target_synset_id' then
    c := c || private.rule('target_synset',
      exists (select 1 from public.synsets y, unnest(y.lemmas) m
              where y.id = p ->> 'target_synset_id' and public.normalize_lemma(m) = public.normalize_lemma(t)),
      'error', null, 'The target synset must contain the related word');
  end if;

  if edge is not null then
    if private.synset_above(edge ->> 'parent', edge ->> 'child') then
      c := c || private.rule('no_cycle', false, 'error', null, 'This would make a synset its own ancestor in the taxonomy');
    elsif private.synset_above(edge ->> 'child', edge ->> 'parent') then
      c := c || jsonb_build_array(jsonb_build_object('code', 'taxonomy', 'level', 'note',
        'message', 'Already below that synset in the taxonomy: the relation is recorded, no edge is added'));
    else
      c := c || jsonb_build_array(jsonb_build_object('code', 'taxonomy', 'level', 'pass',
        'message', format('Adds %s under %s in the taxonomy', edge ->> 'child', edge ->> 'parent')));
    end if;
  end if;

  if ty in ('synonym', 'antonym', 'derived') then
    select r.score into sg from public.relation_suggestions r
    where r.sense_id = s.id and r.type = ty and public.normalize_lemma(r.target_lemma) = public.normalize_lemma(t);
    c := c || private.rule('model_support', false, 'review', null,
      case ty
        when 'synonym' then 'Synonyms are always checked by a moderator: the model cannot tell a synonym from a sister term'
        else 'Antonyms and derived forms are always checked by a moderator'
      end);
    if sg.score is not null then
      c := c || jsonb_build_array(jsonb_build_object('code', 'model_note', 'level', 'note',
        'message', format('LexSPLADE lists “%s” as a near-synonym (score %s)', t, round(sg.score::numeric, 2))));
    end if;
  elsif ty is not null and t is not null then
    select r.score into sg from public.relation_suggestions r
    where r.sense_id = s.id and r.type = ty and public.normalize_lemma(r.target_lemma) = public.normalize_lemma(t);
    c := c || private.rule('model_support', sg.score >= 0.6, 'review',
      format('LexSPLADE suggests this %s (score %s)', ty, round(sg.score::numeric, 2)),
      case when sg.score is null
        then 'Not among LexSPLADE’s suggestions for this sense; a moderator will check it'
        else format('LexSPLADE gives it a low score (%s); a moderator will check it', round(sg.score::numeric, 2))
      end);
  end if;

  if uid is not null then
    select count(*) filter (where status = 'accepted'), count(*) filter (where status = 'rejected')
      into accepted, rejected
    from public.contributions where contributor_id = uid;
    c := c || private.rule('trusted', accepted >= 3 and rejected = 0, 'review',
      'Contributor has 3 or more accepted contributions and none rejected',
      'Relations from contributors with fewer than 3 accepted contributions are reviewed by a moderator');
  end if;
  return c;
end;
$$;

-- ---------- Publishing ----------

create function private.publish_relation(r public.contributions, m public.validation_method, reviewer uuid, note text)
returns public.contributions
language plpgsql
volatile
set search_path = ''
as $$
declare
  p jsonb := r.payload;
  ty text := p ->> 'type';
  t text := p ->> 'target_lemma';
  edge jsonb := private.relation_edge(p);
  done jsonb;
begin
  if ty = 'synonym' then
    insert into public.sense_lemmas (sense_id, lemma, position)
    select r.sense_id, t, coalesce(max(position) + 1, 0) from public.sense_lemmas where sense_id = r.sense_id;
    done := jsonb_build_object('table', 'sense_lemmas', 'lemma', t);
  else
    insert into public.relations (sense_id, type, target_lemma, position)
    select r.sense_id, ty::public.relation_type, t, coalesce(max(position) + 1, 0)
    from public.relations where sense_id = r.sense_id and type::text = ty;
    done := jsonb_build_object('table', 'relations', 'type', ty, 'target_lemma', t);
  end if;

  if edge is not null and not private.synset_above(edge ->> 'child', edge ->> 'parent') then
    insert into public.synset_hypernyms (synset_id, hypernym_id, position)
    select edge ->> 'child', edge ->> 'parent', coalesce(max(position) + 1, 0)
    from public.synset_hypernyms where synset_id = edge ->> 'child';
    done := done || jsonb_build_object('synset_edge', edge);
  end if;

  update public.contributions
  set status = 'accepted', validation = m, published = done, reviewer_id = reviewer, review_note = note, decided_at = now()
  where id = r.id
  returning * into r;
  return r;
end;
$$;

-- Undo what publish_relation wrote.
create function private.withdraw_relation(r public.contributions)
returns void
language plpgsql
volatile
set search_path = ''
as $$
declare
  d jsonb := r.published;
begin
  if d ->> 'table' = 'sense_lemmas' then
    delete from public.sense_lemmas where sense_id = r.sense_id and lemma = d ->> 'lemma';
  elsif d ->> 'table' = 'relations' then
    delete from public.relations
    where sense_id = r.sense_id and type::text = d ->> 'type' and target_lemma = d ->> 'target_lemma';
  end if;
  if d ? 'synset_edge' then
    delete from public.synset_hypernyms
    where synset_id = d -> 'synset_edge' ->> 'child' and hypernym_id = d -> 'synset_edge' ->> 'parent';
  end if;
end;
$$;

alter function private.publish(public.contributions, public.validation_method, uuid, text) rename to publish_base;

create function private.publish(r public.contributions, m public.validation_method, reviewer uuid, note text)
returns public.contributions
language plpgsql
volatile
set search_path = ''
as $$
begin
  if r.kind::text = 'relation' then
    return private.publish_relation(r, m, reviewer, note);
  end if;
  return private.publish_base(r, m, reviewer, note);
end;
$$;

-- ---------- RPCs ----------

create function public.check_relation(p jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  return private.relation_report(private.clean_relation(p), private.contributor(), null);
end;
$$;

-- Propose a relation: {sense_id, type, target_lemma, target_sense_id?, note?}.
create function public.submit_relation(p jsonb)
returns public.contributions
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  uid uuid := private.contributor();
  v jsonb := private.clean_relation(p);
  c jsonb;
  r public.contributions;
begin
  perform pg_advisory_xact_lock(hashtext('shiftnet.contributor:' || uid::text));
  if length(v ->> 'note') > 500 then
    raise exception 'Note: at most 500 characters' using errcode = '22023';
  end if;
  c := private.relation_report(v, uid, null);
  perform private.raise_on_errors(c);
  insert into public.contributions (contributor_id, kind, lemma, sense_id, payload, checks)
  select uid, 'relation'::text::public.contribution_kind, s.lemma, s.id, v, c from public.senses s where s.id = v ->> 'sense_id'
  returning * into r;
  if not private.has_level(c, 'review') then
    r := private.publish(r, 'automatic', null, null);
  end if;
  return r;
end;
$$;

-- Moderation: relations here, usages and senses in the original function.
alter function public.review_contribution(uuid, text, text) set schema private;
alter function private.review_contribution(uuid, text, text) rename to review_contribution_base;

create function public.review_contribution(p_id uuid, p_decision text, p_note text default null)
returns public.contributions
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  uid uuid;
  note text := private.clean(p_note);
  r public.contributions;
  c jsonb;
begin
  select * into r from public.contributions where id = p_id;
  if not found or r.kind::text <> 'relation' then
    return private.review_contribution_base(p_id, p_decision, p_note);
  end if;

  uid := private.contributor();
  if not private.is_moderator(uid) then
    raise exception 'Only moderators can review contributions' using errcode = '42501';
  end if;
  if p_decision is null or p_decision not in ('accept', 'reject') then
    raise exception 'Decision must be accept or reject' using errcode = '22023';
  end if;
  if length(note) > 1000 then
    raise exception 'Review note: at most 1,000 characters' using errcode = '22023';
  end if;
  select * into r from public.contributions where id = p_id for update;
  if r.contributor_id = uid then
    raise exception 'Another moderator must review your own contributions' using errcode = '42501';
  end if;
  if p_decision = 'reject' and note is null then
    raise exception 'Say why the contribution is rejected; the contributor sees the note' using errcode = '22023';
  end if;

  if r.status = 'pending' and p_decision = 'accept' then
    c := private.relation_report(r.payload, null, r.id);
    perform private.raise_on_errors(c);
    update public.contributions set checks = c where id = r.id returning * into r;
    r := private.publish(r, 'manual', uid, note);
  elsif r.status = 'pending' then
    update public.contributions
    set status = 'rejected', reviewer_id = uid, review_note = note, decided_at = now()
    where id = r.id returning * into r;
  elsif r.status = 'accepted' and r.validation = 'automatic' and p_decision = 'accept' then
    update public.contributions
    set validation = 'manual', reviewer_id = uid, review_note = note, decided_at = now()
    where id = r.id returning * into r;
  elsif r.status = 'accepted' and r.validation = 'automatic' then
    perform private.withdraw_relation(r);
    update public.contributions
    set status = 'rejected', validation = null, published = null, reviewer_id = uid, review_note = note, decided_at = now()
    where id = r.id returning * into r;
  else
    raise exception 'This contribution has already been reviewed' using errcode = '55000';
  end if;
  return r;
end;
$$;

-- ---------- Access ----------

alter table public.relation_suggestions enable row level security;
create policy "Signed-in users can read relation suggestions" on public.relation_suggestions
  for select to authenticated using (true);
revoke all on public.relation_suggestions from anon, authenticated;
grant select on public.relation_suggestions to authenticated;

revoke execute on all functions in schema private from public, anon, authenticated;
revoke execute on function public.check_relation(jsonb), public.submit_relation(jsonb), public.review_contribution(uuid, text, text)
  from public, anon;
grant execute on function public.check_relation(jsonb), public.submit_relation(jsonb), public.review_contribution(uuid, text, text)
  to authenticated;
