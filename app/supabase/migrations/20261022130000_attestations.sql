-- Attestations: dated quotations showing a sense in use, each pointing to a reference
-- (book, website, article …). Also records how each published row was validated.

create type public.reference_kind as enum (
  'book', 'website', 'article', 'journal', 'newspaper', 'dictionary', 'corpus', 'archive', 'other'
);
-- How a published row was checked: by the ShiftNet team when loaded, by the automatic
-- checks on a contribution, or by a moderator reviewing a contribution.
create type public.validation_method as enum ('editorial', 'automatic', 'manual');

alter table public.senses
  add column validation public.validation_method not null default 'editorial';

-- A cited work. Shared by every attestation quoted from it.
create table public.sources (
  id uuid primary key default gen_random_uuid(),
  kind public.reference_kind not null,
  title text not null,
  author text,
  publisher text,                            -- publisher, site name, journal or newspaper
  published_label text,                      -- as recorded: '1965', 'March 1990', 'c. 1400'
  published_year integer,
  url text,
  identifier text,                           -- ISBN, DOI, archive shelfmark …
  accessed_on date,                          -- for websites
  created_at timestamptz not null default now(),
  constraint sources_title_not_blank check (length(trim(title)) > 0),
  constraint sources_url_http check (url is null or url ~* '^https?://')
);

create table public.attestations (
  id uuid primary key default gen_random_uuid(),
  sense_id text not null references public.senses (id) on delete cascade,
  source_id uuid not null references public.sources (id) on delete restrict,
  quote text not null,                       -- the sentence(s) showing the sense in use
  year integer,                              -- year of the quoted use, for ordering
  date_label text,                           -- as recorded, when more precise or vaguer than the year
  locator text,                              -- page, chapter, section or timestamp
  relevance_override real,                   -- editorial ranking; replaces the computed score when set
  relevance real not null default 0,         -- maintained by trigger, 0–1; higher shows first
  validation public.validation_method not null default 'editorial',
  validated_at timestamptz,
  created_at timestamptz not null default now(),
  constraint attestations_quote_not_blank check (length(trim(quote)) > 0),
  constraint attestations_relevance_range check (relevance_override is null or relevance_override between 0 and 1)
);

create index attestations_sense_rank_idx on public.attestations (sense_id, relevance desc, year);
create index attestations_source_idx on public.attestations (source_id);

-- Relevance used to pick the quotations shown first (the word page shows the top 3).
-- Rewards a quote that contains the head word, a checked row, a citable kind of source,
-- a known date, a readable length and early evidence (within 50 years of the sense's registration).
create function public.attestation_relevance(a public.attestations)
returns real
language sql
stable
set search_path = ''
as $$
  select coalesce(a.relevance_override, (
    (case when public.normalize_lemma(a.quote) like '%' || public.normalize_lemma(s.lemma) || '%' then 0.3 else 0 end)
    + (case a.validation when 'automatic' then 0.1 else 0.2 end)
    + (case src.kind
         when 'book' then 0.15 when 'journal' then 0.15 when 'dictionary' then 0.15
         when 'article' then 0.1 when 'newspaper' then 0.1 when 'corpus' then 0.1 when 'archive' then 0.1
         when 'website' then 0.07
         else 0.05
       end)
    + (case when a.year is not null then 0.1 else 0 end)
    + (case when length(a.quote) between 40 and 200 then 0.15 when length(a.quote) between 20 and 300 then 0.1 else 0.05 end)
    + (case when a.year between s.date_earliest and s.date_earliest + 50 then 0.1 else 0 end)
  )::real)
  from public.senses s, public.sources src
  where s.id = a.sense_id and src.id = a.source_id
$$;

create function public.set_attestation_relevance()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.relevance := coalesce(public.attestation_relevance(new), 0);
  return new;
end;
$$;

create trigger attestations_relevance before insert or update on public.attestations
  for each row execute function public.set_attestation_relevance();

-- Attestations in display order per sense: by relevance, but a work's second quotation comes
-- after every other work's best one, so the top 3 are not three lines of the same book.
-- `rank` starts at 1; `total` is the sense's attestation count. The source is inlined as JSON.
create view public.ranked_attestations
with (security_invoker = true)
as
select
  id, sense_id, quote, year, date_label, locator, relevance, validation, source,
  row_number() over (partition by sense_id order by source_rank > 1, relevance desc, year nulls last, id)::integer as rank,
  count(*) over (partition by sense_id)::integer as total
from (
  select a.*,
    jsonb_build_object(
      'id', src.id, 'kind', src.kind, 'title', src.title, 'author', src.author, 'publisher', src.publisher,
      'published_label', src.published_label, 'published_year', src.published_year, 'url', src.url,
      'identifier', src.identifier, 'accessed_on', src.accessed_on
    ) as source,
    row_number() over (partition by a.sense_id, a.source_id order by a.relevance desc, a.year nulls last, a.id) as source_rank
  from public.attestations a
  join public.sources src on src.id = a.source_id
) t;

alter table public.sources enable row level security;
alter table public.attestations enable row level security;

create policy "Sources are readable by everyone" on public.sources
  for select to anon, authenticated using (true);
create policy "Attestations are readable by everyone" on public.attestations
  for select to anon, authenticated using (true);

grant select on public.sources, public.attestations, public.ranked_attestations to anon, authenticated;

revoke execute on function public.set_attestation_relevance() from public, anon, authenticated;
grant execute on function public.attestation_relevance(public.attestations) to anon, authenticated;
