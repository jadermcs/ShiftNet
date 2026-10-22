-- ShiftNet schema: WordNet senses with a registration date and parent senses.
-- Read-only for the public (PRD: open access, no editing from the interface).

create extension if not exists unaccent with schema extensions;
create extension if not exists pg_trgm with schema extensions;
create extension if not exists fuzzystrmatch with schema extensions;

create type public.part_of_speech as enum ('noun', 'verb', 'adjective', 'adverb');
create type public.shift_type as enum (
  'root', 'broadening', 'narrowing', 'metaphor', 'metonymy', 'amelioration', 'pejoration', 'other'
);
create type public.source_type as enum ('dictionary', 'corpus', 'citation');
create type public.relation_type as enum ('antonym', 'hypernym', 'hyponym', 'meronym', 'holonym', 'derived');

-- Case- and accent-insensitive key used by search.
create function public.normalize_lemma(t text)
returns text
language sql
immutable
parallel safe
set search_path = ''
as $$
  select lower(trim(extensions.unaccent('extensions.unaccent'::regdictionary, t)))
$$;

create table public.senses (
  id text primary key,                       -- stable id used in URLs, e.g. cloud.n.02
  lemma text not null,                       -- head word of the entry
  pos public.part_of_speech not null,
  gloss text not null,
  examples text[] not null default '{}',
  date_label text not null,                  -- as recorded: '1965', 'c. 1300', '16th c.'
  date_earliest integer not null,            -- earliest possible year; rows sort on this
  obsolete_year integer,
  obsolete_label text,
  shift public.shift_type not null default 'root',
  source text not null,                      -- provenance of the date
  source_type public.source_type not null,
  sense_num integer,                         -- maintained by trigger: n. 1, n. 2 … per lemma and pos
  branch smallint,                           -- maintained by trigger: 0–7, registration order within the lemma
  created_at timestamptz not null default now(),
  constraint senses_obsolete_after_registration check (obsolete_year is null or obsolete_year >= date_earliest)
);

create index senses_lemma_idx on public.senses (lemma, date_earliest, id);
create index senses_timeline_idx on public.senses (date_earliest desc, id);
create index senses_lemma_trgm_idx on public.senses using gin (public.normalize_lemma(lemma) extensions.gin_trgm_ops);

create table public.sense_parents (
  sense_id text not null,
  parent_id text not null,
  position smallint not null default 0,      -- 0 = the branch the sense grows from; >0 = merged parents
  source text,                               -- provenance of the parent link
  constraint sense_parents_pkey primary key (sense_id, parent_id),
  constraint sense_parents_sense_id_fkey foreign key (sense_id) references public.senses (id) on delete cascade,
  constraint sense_parents_parent_id_fkey foreign key (parent_id) references public.senses (id) on delete cascade,
  constraint sense_parents_not_self check (sense_id <> parent_id)
);

create index sense_parents_parent_idx on public.sense_parents (parent_id);

-- Synset members (synonyms), including multi-word expressions such as "cloud computing".
create table public.sense_lemmas (
  sense_id text not null references public.senses (id) on delete cascade,
  lemma text not null,
  position smallint not null default 0,
  primary key (sense_id, lemma)
);

create index sense_lemmas_trgm_idx on public.sense_lemmas using gin (public.normalize_lemma(lemma) extensions.gin_trgm_ops);

create table public.relations (
  sense_id text not null references public.senses (id) on delete cascade,
  type public.relation_type not null,
  target_lemma text not null,
  position smallint not null default 0,
  primary key (sense_id, type, target_lemma)
);

-- Keep sense_num and branch in step with registration order.
create function public.renumber_senses()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  update public.senses s
  set sense_num = r.sense_num, branch = r.branch
  from (
    select id,
      row_number() over (partition by lemma, pos order by date_earliest, id) as sense_num,
      (row_number() over (partition by lemma order by date_earliest, id) - 1) % 8 as branch
    from public.senses
  ) r
  where s.id = r.id
    and (s.sense_num is distinct from r.sense_num or s.branch is distinct from r.branch);
  return null;
end;
$$;

create trigger senses_renumber_insert after insert on public.senses
  for each statement execute function public.renumber_senses();
create trigger senses_renumber_update after update of lemma, pos, date_earliest on public.senses
  for each statement execute function public.renumber_senses();
create trigger senses_renumber_delete after delete on public.senses
  for each statement execute function public.renumber_senses();

-- One row per head word.
create view public.words
with (security_invoker = true)
as
select
  lemma,
  array_agg(distinct pos order by pos) as pos,
  count(*)::integer as sense_count,
  min(date_earliest) as first_year
from public.senses
group by lemma;

-- Period used for the global timeline's year separators.
create function public.period_label(y integer)
returns text
language sql
immutable
parallel safe
set search_path = ''
as $$
  select case
    when y < 1100 then 'Old English'
    when y >= 1900 then (y / 10 * 10)::text || 's'
    else (y / 100 + 1)::text
      || case
           when (y / 100 + 1) % 100 in (11, 12, 13) then 'th'
           when (y / 100 + 1) % 10 = 1 then 'st'
           when (y / 100 + 1) % 10 = 2 then 'nd'
           when (y / 100 + 1) % 10 = 3 then 'rd'
           else 'th'
         end
      || ' century'
  end
$$;

-- Suggestions: head words and multi-word expressions / synonyms that contain the query.
create function public.search_lemmas(q text, max_results integer default 8)
returns table (lemma text, kind text, sense_id text, pos text, meta text)
language sql
stable
set search_path = ''
as $$
  with n as (
    select public.normalize_lemma(q) as q,
      '%' || replace(replace(replace(public.normalize_lemma(q), '\', '\\'), '%', '\%'), '_', '\_') || '%' as pattern
  ),
  heads as (
    select s.lemma,
      'word'::text as kind,
      null::text as sense_id,
      (select string_agg(p::text, ' · ' order by p) from unnest(array_agg(distinct s.pos)) p) as pos,
      count(*) || case when count(*) = 1 then ' sense' else ' senses' end as meta,
      case when public.normalize_lemma(s.lemma) like (n.q || '%') then 0 else 1 end as score
    from public.senses s, n
    where length(n.q) >= 2 and public.normalize_lemma(s.lemma) like n.pattern
    group by s.lemma, n.q
  ),
  expressions as (
    select distinct on (public.normalize_lemma(l.lemma))
      l.lemma,
      'sense'::text,
      s.id,
      s.pos::text,
      'sense of ' || s.lemma,
      case when public.normalize_lemma(l.lemma) like (n.q || '%') then 0 else 2 end
    from public.sense_lemmas l
    join public.senses s on s.id = l.sense_id, n
    where length(n.q) >= 2
      and public.normalize_lemma(l.lemma) like n.pattern
      and not exists (
        select 1 from public.senses h where public.normalize_lemma(h.lemma) = public.normalize_lemma(l.lemma)
      )
    order by public.normalize_lemma(l.lemma), s.date_earliest, s.id
  )
  select lemma, kind, sense_id, pos, meta
  from (select * from heads union all select * from expressions) r
  order by score, lemma
  limit max_results
$$;

-- Close spellings for a query with no match.
create function public.close_spellings(q text, max_results integer default 5)
returns table (lemma text, kind text, sense_id text)
language sql
stable
set search_path = ''
as $$
  with n as (
    select public.normalize_lemma(q) as q,
      greatest(2, ceil(length(public.normalize_lemma(q)) / 3.0)::integer) as max_d
  ),
  candidates as (
    select distinct lemma, 'word'::text as kind, null::text as sense_id from public.senses
    union all
    select distinct on (public.normalize_lemma(l.lemma)) l.lemma, 'sense', l.sense_id
    from public.sense_lemmas l
    where not exists (
      select 1 from public.senses h where public.normalize_lemma(h.lemma) = public.normalize_lemma(l.lemma)
    )
  )
  select c.lemma, c.kind, c.sense_id
  from candidates c, n,
    lateral (select extensions.levenshtein_less_equal(n.q, public.normalize_lemma(c.lemma), n.max_d) as d) dist
  where length(n.q) > 0 and dist.d <= n.max_d
  order by dist.d, c.lemma
  limit max_results
$$;

-- Exact lookup ignoring case and accents: a head word, else an expression's sense.
create function public.resolve_lemma(q text)
returns table (kind text, lemma text, sense_id text)
language sql
stable
set search_path = ''
as $$
  (select 'word'::text, s.lemma, null::text
   from public.senses s
   where public.normalize_lemma(s.lemma) = public.normalize_lemma(q)
   limit 1)
  union all
  (select 'sense', l.lemma, l.sense_id
   from public.sense_lemmas l
   join public.senses s on s.id = l.sense_id
   where public.normalize_lemma(l.lemma) = public.normalize_lemma(q)
   order by s.date_earliest, s.id
   limit 1)
  limit 1
$$;

-- Period separators for "Jump to": label and how many newer senses come before it.
create function public.timeline_periods()
returns table (label text, row_offset integer)
language sql
stable
set search_path = ''
as $$
  select label, (min(rn) - 1)::integer
  from (
    select public.period_label(date_earliest) as label,
      row_number() over (order by date_earliest desc, id) as rn
    from public.senses
  ) t
  group by label
  order by 2
$$;

-- Public read-only access. Tables are not exposed to the Data API automatically,
-- so grants are explicit; RLS allows reads and nothing else.
alter table public.senses enable row level security;
alter table public.sense_parents enable row level security;
alter table public.sense_lemmas enable row level security;
alter table public.relations enable row level security;

create policy "Senses are readable by everyone" on public.senses
  for select to anon, authenticated using (true);
create policy "Parent links are readable by everyone" on public.sense_parents
  for select to anon, authenticated using (true);
create policy "Synset members are readable by everyone" on public.sense_lemmas
  for select to anon, authenticated using (true);
create policy "Relations are readable by everyone" on public.relations
  for select to anon, authenticated using (true);

grant usage on schema public to anon, authenticated;
grant select on public.senses, public.sense_parents, public.sense_lemmas, public.relations, public.words
  to anon, authenticated;

revoke execute on function public.renumber_senses() from public, anon, authenticated;
grant execute on function
  public.normalize_lemma(text),
  public.period_label(integer),
  public.search_lemmas(text, integer),
  public.close_spellings(text, integer),
  public.resolve_lemma(text),
  public.timeline_periods()
  to anon, authenticated;
