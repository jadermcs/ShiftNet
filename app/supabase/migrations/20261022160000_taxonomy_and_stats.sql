-- WordNet taxonomy: synsets linked by hypernym edges, so a sense can be placed in the
-- tree (entity › … › atmospheric phenomenon › cloud) and its hyponyms browsed.
-- Also lexicon-wide statistics for the /stats page.
--
-- Synset ids follow Open English WordNet where a synset comes from it (oewn-11458314-n);
-- the sample seed uses readable ids (wn-atmospheric_phenomenon-n) and gives each dated
-- sense its own synset, with the sense id as the synset id.

create table public.synsets (
  id text primary key,
  pos public.part_of_speech not null,
  lemmas text[] not null,                    -- members; the first one names the synset
  gloss text,
  constraint synsets_lemmas_not_empty check (cardinality(lemmas) > 0)
);

create table public.synset_hypernyms (
  synset_id text not null,
  hypernym_id text not null,
  position smallint not null default 0,      -- 0 = the path shown in breadcrumbs; >0 = also under
  constraint synset_hypernyms_pkey primary key (synset_id, hypernym_id),
  constraint synset_hypernyms_synset_id_fkey foreign key (synset_id) references public.synsets (id) on delete cascade,
  constraint synset_hypernyms_hypernym_id_fkey foreign key (hypernym_id) references public.synsets (id) on delete cascade,
  constraint synset_hypernyms_not_self check (synset_id <> hypernym_id)
);

create index synset_hypernyms_hypernym_idx on public.synset_hypernyms (hypernym_id);

-- The synset a dated sense belongs to. Null until the sense is placed in the taxonomy
-- (e.g. a contributed sense waiting for an editor).
alter table public.senses
  add column synset_id text references public.synsets (id) on delete set null;

create index senses_synset_idx on public.senses (synset_id);

-- A synset and its ancestors along the first hypernym, root first; depth 0 is the synset itself.
create function public.synset_path(target text)
returns table (depth integer, id text, pos public.part_of_speech, lemmas text[], gloss text)
language sql
stable
set search_path = ''
as $$
  with recursive up as (
    select 0 as depth, s.id, array[s.id] as seen
    from public.synsets s
    where s.id = target
    union all
    select up.depth + 1, h.hypernym_id, up.seen || h.hypernym_id
    from up
    join public.synset_hypernyms h on h.synset_id = up.id and h.position = 0
    where h.hypernym_id <> all (up.seen) and up.depth < 50
  )
  select up.depth, s.id, s.pos, s.lemmas, s.gloss
  from up
  join public.synsets s on s.id = up.id
  order by up.depth desc
$$;

-- A synset as listed in the taxonomy: how many hyponyms it has (can it be opened further?)
-- and its dated senses, with the earliest one's date as recorded.
create view public.synset_cards
with (security_invoker = true)
as
select s.id, s.pos, s.lemmas, s.gloss,
  (select count(*)::integer from public.synset_hypernyms c where c.hypernym_id = s.id) as hyponym_count,
  d.sense_count,
  d.first_year,
  d.first_label
from public.synsets s
cross join lateral (
  select count(*)::integer as sense_count,
    min(x.date_earliest) as first_year,
    (array_agg(x.date_label order by x.date_earliest, x.id))[1] as first_label
  from public.senses x
  where x.synset_id = s.id
) d;

-- Direct hyponyms of a synset, oldest dated sense first, then undated ones by name.
create function public.synset_hyponyms(target text)
returns setof public.synset_cards
language sql
stable
set search_path = ''
as $$
  select c.*
  from public.synset_hypernyms h
  join public.synset_cards c on c.id = h.synset_id
  where h.hypernym_id = target
  order by c.first_year nulls last, lower(c.lemmas[1]), c.id
$$;

-- Tops of the taxonomy: synsets with hyponyms but no hypernym (entity for nouns, several for verbs).
-- Synsets with neither, such as adjectives, are left out.
create function public.synset_roots()
returns setof public.synset_cards
language sql
stable
set search_path = ''
as $$
  select c.*
  from public.synset_cards c
  where c.hyponym_count > 0
    and not exists (select 1 from public.synset_hypernyms h where h.synset_id = c.id)
  order by c.pos, lower(c.lemmas[1]), c.id
$$;

-- Statistics. Every figure about change uses the primary parent link (position 0),
-- the branch a sense grows from.

-- Head figures for the stats page.
create function public.stats_overview()
returns table (
  senses integer, words integer, links integer, obsolete integer,
  pos_changes integer, cross_word integer, median_gap integer
)
language sql
stable
set search_path = ''
as $$
  select
    (select count(*)::integer from public.senses),
    (select count(distinct lemma)::integer from public.senses),
    count(l.child_id)::integer,
    (select count(*)::integer from public.senses where obsolete_year is not null),
    count(*) filter (where l.child_pos <> l.parent_pos)::integer,
    count(*) filter (where l.child_lemma <> l.parent_lemma)::integer,
    round(percentile_cont(0.5) within group (order by l.gap))::integer
  from (
    select c.id as child_id, c.pos as child_pos, p.pos as parent_pos, c.lemma as child_lemma, p.lemma as parent_lemma,
      c.date_earliest - p.date_earliest as gap
    from public.sense_parents sp
    join public.senses c on c.id = sp.sense_id
    join public.senses p on p.id = sp.parent_id
    where sp.position = 0
  ) l
$$;

-- New senses per period and shift type. Periods follow the global timeline's separators:
-- Old English, then centuries, then decades from 1900.
create function public.stats_periods()
returns table (period text, period_start integer, shift public.shift_type, senses integer)
language sql
stable
set search_path = ''
as $$
  select g.period, min(g.first) over (partition by g.period)::integer, g.shift, g.n
  from (
    select public.period_label(date_earliest) as period, shift, min(date_earliest) as first, count(*)::integer as n
    from public.senses
    group by 1, 2
  ) g
  order by 2, 3
$$;

-- Per shift type: how many senses, how many are obsolete, and the time from parent to child.
create function public.stats_shifts()
returns table (
  shift public.shift_type, senses integer, obsolete integer,
  median_gap integer, min_gap integer, max_gap integer, pos_changes integer, cross_word integer
)
language sql
stable
set search_path = ''
as $$
  select c.shift,
    count(*)::integer,
    count(*) filter (where c.obsolete_year is not null)::integer,
    -- null for root senses, which percentile_cont skips
    round(percentile_cont(0.5) within group (order by c.date_earliest - p.date_earliest))::integer,
    min(c.date_earliest - p.date_earliest)::integer,
    max(c.date_earliest - p.date_earliest)::integer,
    count(*) filter (where p.pos <> c.pos)::integer,
    count(*) filter (where p.lemma <> c.lemma)::integer
  from public.senses c
  left join public.sense_parents sp on sp.sense_id = c.id and sp.position = 0
  left join public.senses p on p.id = sp.parent_id
  group by c.shift
  order by c.shift
$$;

-- Part of speech of the parent sense against the child's.
create function public.stats_pos_transitions()
returns table (from_pos public.part_of_speech, to_pos public.part_of_speech, links integer)
language sql
stable
set search_path = ''
as $$
  select p.pos, c.pos, count(*)::integer
  from public.sense_parents sp
  join public.senses c on c.id = sp.sense_id
  join public.senses p on p.id = sp.parent_id
  where sp.position = 0
  group by 1, 2
  order by 1, 2
$$;

alter table public.synsets enable row level security;
alter table public.synset_hypernyms enable row level security;

create policy "Synsets are readable by everyone" on public.synsets
  for select to anon, authenticated using (true);
create policy "Hypernym links are readable by everyone" on public.synset_hypernyms
  for select to anon, authenticated using (true);

grant select on public.synsets, public.synset_hypernyms, public.synset_cards to anon, authenticated;

grant execute on function
  public.synset_path(text),
  public.synset_hyponyms(text),
  public.synset_roots(),
  public.stats_overview(),
  public.stats_periods(),
  public.stats_shifts(),
  public.stats_pos_transitions()
  to anon, authenticated;
