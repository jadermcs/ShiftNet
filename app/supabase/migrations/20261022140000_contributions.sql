-- Community contributions: proposed usages (attestations of an existing sense) and proposed senses.
--
-- Contributors (signed-in, non-anonymous users) submit through security definer RPCs that run the
-- automatic checks server side. Each check yields one of:
--   error   the submission is refused and nothing is stored (missing field, bad URL, duplicate …)
--   review  stored as pending; a moderator accepts or rejects it (antedating, lemma not in quote …)
--   note    shown to the contributor and moderators, no effect on the outcome
--   pass    recorded so the interface can show what was checked
-- A submission with no error and no review flag is published at once with validation 'automatic';
-- one a moderator accepts is published with validation 'manual'. Moderators can also confirm
-- (automatic → manual) or withdraw an auto-accepted contribution.

create type public.contribution_kind as enum ('usage', 'sense');
create type public.contribution_status as enum ('pending', 'accepted', 'rejected');

-- Helpers live in a schema that is not exposed through the Data API.
create schema if not exists private;
revoke all on schema private from public;

-- Who may review. Rows are added by the ShiftNet team with a privileged connection.
create table public.moderators (
  user_id uuid primary key references auth.users (id) on delete cascade,
  note text,
  added_at timestamptz not null default now()
);

create table public.contributions (
  id uuid primary key default gen_random_uuid(),
  contributor_id uuid not null references auth.users (id) on delete cascade,
  kind public.contribution_kind not null,
  status public.contribution_status not null default 'pending',
  lemma text not null,                       -- head word concerned, for listing
  sense_id text references public.senses (id) on delete set null,          -- usage: target sense; sense: the sense created on acceptance
  attestation_id uuid references public.attestations (id) on delete set null, -- the published quotation, once accepted
  payload jsonb not null,                    -- the proposal, normalised by private.clean_usage / private.clean_sense
  checks jsonb not null default '[]',        -- [{code, level, message}] from the latest run of the automatic checks
  validation public.validation_method,       -- set when accepted: automatic or manual
  reviewer_id uuid references auth.users (id) on delete set null, -- null when decided by the automatic checks
  review_note text,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  constraint contributions_validation_iff_accepted check ((status = 'accepted') = (validation is not null)),
  constraint contributions_not_editorial check (validation is distinct from 'editorial'),
  constraint contributions_note_length check (review_note is null or length(review_note) <= 1000)
);

create index contributions_contributor_idx on public.contributions (contributor_id, created_at desc);
create index contributions_queue_idx on public.contributions (created_at) where status = 'pending';
create index contributions_unconfirmed_idx on public.contributions (decided_at desc)
  where status = 'accepted' and validation = 'automatic';
create index contributions_sense_idx on public.contributions (sense_id);
create index contributions_reviewer_idx on public.contributions (reviewer_id);

-- ---------- Small helpers ----------

-- Trim, turn control characters into spaces, collapse whitespace; '' becomes null.
create function private.clean(t text)
returns text
language sql
immutable
set search_path = ''
as $$
  select nullif(btrim(regexp_replace(regexp_replace(t, '[[:cntrl:]]', ' ', 'g'), '\s+', ' ', 'g')), '')
$$;

create function private.to_int(t text)
returns integer
language plpgsql
immutable
set search_path = ''
as $$
begin
  return btrim(t)::integer;
exception when others then
  return null;
end;
$$;

create function private.to_date(t text)
returns date
language plpgsql
immutable
set search_path = ''
as $$
begin
  return btrim(t)::date;
exception when others then
  return null;
end;
$$;

-- A whole number as jsonb; a value that is not one is kept as a string so the checks can report it.
create function private.clean_int(v jsonb)
returns jsonb
language sql
immutable
set search_path = ''
as $$
  select case
    when private.clean(v #>> '{}') is null then null
    when private.to_int(v #>> '{}') is not null then to_jsonb(private.to_int(v #>> '{}'))
    else to_jsonb(v #>> '{}')
  end
$$;

create function private.clean_date(v jsonb)
returns jsonb
language sql
immutable
set search_path = ''
as $$
  select case
    when private.clean(v #>> '{}') is null then null
    when private.to_date(v #>> '{}') is not null then to_jsonb(private.to_date(v #>> '{}')::text)
    else to_jsonb('invalid:' || (v #>> '{}'))
  end
$$;

-- Key for comparing quotes and glosses: letters and digits only, lower case, no accents.
create function private.text_key(t text)
returns text
language sql
immutable
set search_path = ''
as $$
  select public.normalize_lemma(regexp_replace(coalesce(t, ''), '[^[:alnum:]]+', ' ', 'g'))
$$;

-- One check result, as a 0- or 1-element array so results concatenate with ||.
-- A null condition counts as failed; a null pass message records nothing on success.
create function private.rule(code text, ok boolean, fail_level text, pass_msg text, fail_msg text)
returns jsonb
language sql
immutable
set search_path = ''
as $$
  select case
    when coalesce(ok, false) and pass_msg is null then '[]'::jsonb
    when coalesce(ok, false) then jsonb_build_array(jsonb_build_object('code', code, 'level', 'pass', 'message', pass_msg))
    else jsonb_build_array(jsonb_build_object('code', code, 'level', fail_level, 'message', fail_msg))
  end
$$;

create function private.has_level(checks jsonb, lvl text)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select exists (select 1 from jsonb_array_elements(checks) e where e ->> 'level' = lvl)
$$;

create function private.raise_on_errors(checks jsonb)
returns void
language plpgsql
immutable
set search_path = ''
as $$
begin
  if private.has_level(checks, 'error') then
    raise exception 'The contribution did not pass the automatic checks'
      using errcode = 'P0001',
        detail = (select jsonb_agg(e)::text from jsonb_array_elements(checks) e where e ->> 'level' = 'error'),
        hint = 'Correct the fields listed and submit again.';
  end if;
end;
$$;

-- Does the quote contain one of the forms, or a plausible inflection (clouds, clouded, nicer, trolling)?
-- Prefix match at a word start; a final -e or -y is dropped from longer forms (nice → nicer, nicest).
create function private.mentions(quote text, forms text[])
returns boolean
language sql
immutable
set search_path = ''
as $$
  select exists (
    select 1
    from unnest(forms) f,
      lateral (select public.normalize_lemma(f) as n) n,
      lateral (select case when length(n.n) > 3 and right(n.n, 1) in ('e', 'y') then left(n.n, -1) else n.n end as stem) s
    where length(s.stem) > 0
      and public.normalize_lemma(quote) ~ ('\m' || regexp_replace(s.stem, '([^[:alnum:][:space:]])', '\\\1', 'g'))
  )
$$;

-- ISBN-10 / ISBN-13 checksum. Null when the text does not look like an ISBN at all.
create function private.isbn_ok(t text)
returns boolean
language plpgsql
immutable
set search_path = ''
as $$
declare
  d text := upper(regexp_replace(regexp_replace(t, '^\s*isbn(-1[03])?:?', '', 'i'), '[- ]', '', 'g'));
  s integer := 0;
begin
  if d ~ '^[0-9]{9}[0-9X]$' then
    for i in 1..10 loop
      s := s + (11 - i) * case when substr(d, i, 1) = 'X' then 10 else substr(d, i, 1)::integer end;
    end loop;
    return s % 11 = 0;
  elsif d ~ '^[0-9]{13}$' then
    for i in 1..13 loop
      s := s + substr(d, i, 1)::integer * case when i % 2 = 1 then 1 else 3 end;
    end loop;
    return d ~ '^97[89]' and s % 10 = 0;
  end if;
  return null;
end;
$$;

-- ---------- Normalising a proposal ----------

create function private.clean_source(s jsonb)
returns jsonb
language sql
immutable
set search_path = ''
as $$
  select jsonb_strip_nulls(jsonb_build_object(
    'kind', private.clean(s ->> 'kind'),
    'title', private.clean(s ->> 'title'),
    'author', private.clean(s ->> 'author'),
    'publisher', private.clean(s ->> 'publisher'),
    'published_label', private.clean(s ->> 'published_label'),
    'published_year', private.clean_int(s -> 'published_year'),
    'url', private.clean(s ->> 'url'),
    'identifier', private.clean(s ->> 'identifier'),
    'accessed_on', private.clean_date(s -> 'accessed_on')
  ))
$$;

-- Only known keys survive; the stored payload is this, never the raw client JSON.
create function private.clean_usage(u jsonb)
returns jsonb
language sql
immutable
set search_path = ''
as $$
  select case when jsonb_typeof(u) = 'object' then jsonb_strip_nulls(jsonb_build_object(
    'sense_id', private.clean(u ->> 'sense_id'),
    'quote', private.clean(u ->> 'quote'),
    'year', private.clean_int(u -> 'year'),
    'date_label', private.clean(u ->> 'date_label'),
    'locator', private.clean(u ->> 'locator'),
    'source', private.clean_source(case when jsonb_typeof(u -> 'source') = 'object' then u -> 'source' else '{}' end)
  )) end
$$;

create function private.clean_list(a jsonb)
returns jsonb
language sql
immutable
set search_path = ''
as $$
  select coalesce(jsonb_agg(x order by o), '[]')
  from (
    select private.clean(e) as x, min(o) as o
    from jsonb_array_elements_text(case when jsonb_typeof(a) = 'array' then a else '[]' end) with ordinality t(e, o)
    group by 1
  ) t
  where x is not null
$$;

-- An existing head word keeps its spelling ("Cloud" → "cloud").
create function private.clean_sense(p jsonb)
returns jsonb
language sql
stable
set search_path = ''
as $$
  with l as (select private.clean(p ->> 'lemma') as lemma)
  select jsonb_strip_nulls(jsonb_build_object(
    'lemma', coalesce(
      (select s.lemma from public.senses s where public.normalize_lemma(s.lemma) = public.normalize_lemma(l.lemma) order by s.lemma limit 1),
      l.lemma),
    'pos', private.clean(p ->> 'pos'),
    'gloss', private.clean(p ->> 'gloss'),
    'examples', private.clean_list(p -> 'examples'),
    'date_label', private.clean(p ->> 'date_label'),
    'date_earliest', private.clean_int(p -> 'date_earliest'),
    'shift', private.clean(p ->> 'shift'),
    'date_source', private.clean(p ->> 'date_source'),
    'source_type', private.clean(p ->> 'source_type'),
    'parents', private.clean_list(p -> 'parents'),
    'usage', private.clean_usage(p -> 'usage')
  ))
  from l
$$;

-- ---------- Automatic checks ----------

-- The cited work.
create function private.source_checks(s jsonb, use_year integer)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  c jsonb := '[]';
  now_y integer := extract(year from now())::integer;
  url text := s ->> 'url';
  ident text := s ->> 'identifier';
  pub integer := case when jsonb_typeof(s -> 'published_year') = 'number' then (s ->> 'published_year')::integer end;
  acc date := private.to_date(s ->> 'accessed_on');
  isbn boolean := private.isbn_ok(ident);
begin
  c := c
    || private.rule('reference_kind', (s ->> 'kind') = any (enum_range(null::public.reference_kind)::text[]), 'error',
         null, 'Reference: choose what kind of work it is (book, website, article …)')
    || private.rule('reference_title', length(s ->> 'title') between 1 and 300, 'error',
         null, 'Reference: a title of at most 300 characters is required')
    || private.rule('reference_lengths',
         coalesce(length(s ->> 'author'), 0) <= 200 and coalesce(length(s ->> 'publisher'), 0) <= 200
           and coalesce(length(s ->> 'published_label'), 0) <= 40 and coalesce(length(ident), 0) <= 100,
         'error', null, 'Reference: author and publisher at most 200 characters, date 40, identifier 100');
  if s ? 'published_year' then
    c := c || private.rule('reference_year', pub between 600 and now_y, 'error',
      null, format('Reference: the publication year must be a whole year between 600 and %s', now_y));
  end if;
  if url is not null then
    c := c || private.rule('url_format',
      length(url) <= 2000 and url ~* '^https?://[^[:space:]/?#@:]+(\.[^[:space:]/?#@:]+)+(:[0-9]{1,5})?([/?#][^[:space:]]*)?$',
      'error', 'URL is a well-formed http(s) address', 'Reference: the URL must be a full http:// or https:// address');
  end if;
  if (s ->> 'kind') = 'website' then
    c := c || private.rule('website_url', url is not null, 'error', null, 'Reference: a website needs its URL');
    c := c || private.rule('accessed_on', acc is not null, 'note', null, 'Add the date you accessed the page; websites change');
  end if;
  if s ? 'accessed_on' then
    c := c || private.rule('accessed_on_valid', acc between date '1990-01-01' and current_date, 'error',
      null, 'Reference: the access date must be a real date, not in the future');
  end if;
  if isbn is not null then
    c := c || private.rule('isbn', isbn, 'review', 'ISBN checksum is valid', 'The ISBN checksum does not match; a moderator will check it');
  elsif ident ~* '^(doi:\s*|https?://(dx\.)?doi\.org/)?10\.' then
    c := c || private.rule('doi', ident ~* '^(doi:\s*|https?://(dx\.)?doi\.org/)?10\.[0-9]{4,9}/[^[:space:]]+$', 'review',
      'DOI is well formed', 'The DOI does not look well formed; a moderator will check it');
  end if;
  c := c || private.rule('verifiable', url is not null or ident is not null, 'review',
    'Reference has a URL or identifier', 'No URL or identifier (ISBN, DOI, shelfmark): a moderator will check the reference');
  if pub is not null and use_year is not null then
    c := c || private.rule('published_after_use', use_year <= pub, 'review',
      null, format('The use (%s) is dated after the work was published (%s); a moderator will check the dates', use_year, pub));
  end if;
  return c;
end;
$$;

-- A quotation, for an existing sense (p_sense_id) or for a proposed one (p_sense_id null).
-- p_exclude skips the contribution being re-checked in the duplicate test.
create function private.quote_checks(
  u jsonb, p_lemma text, p_forms text[], p_registered integer, p_obsolete integer, p_sense_id text, p_exclude uuid
)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  c jsonb := '[]';
  q text := u ->> 'quote';
  y integer := case when jsonb_typeof(u -> 'year') = 'number' then (u ->> 'year')::integer end;
  now_y integer := extract(year from now())::integer;
begin
  c := c
    || private.rule('quote_length', length(q) between 15 and 1200, 'error',
         null, 'Quote: one or two full sentences, 15 to 1,200 characters')
    || private.rule('year', y between 600 and now_y, 'error',
         null, format('Year of use: a whole year between 600 and %s', now_y))
    || private.rule('label_lengths', coalesce(length(u ->> 'date_label'), 0) <= 40 and coalesce(length(u ->> 'locator'), 0) <= 80,
         'error', null, 'Date as recorded: at most 40 characters; page or locator: at most 80');
  if q is null then
    return c;
  end if;
  if p_sense_id is not null then
    c := c || private.rule('duplicate_quote',
      not exists (
        select 1 from public.attestations a
        where a.sense_id = p_sense_id and private.text_key(a.quote) = private.text_key(q)
      ) and not exists (
        select 1 from public.contributions k
        where k.kind = 'usage' and k.status <> 'rejected' and k.sense_id = p_sense_id
          and k.id is distinct from p_exclude
          and private.text_key(k.payload ->> 'quote') = private.text_key(q)
      ),
      'error', 'Quote is new for this sense', 'This quote is already attested, or already proposed, for this sense');
  end if;
  c := c
    || private.rule('mentions_lemma', private.mentions(q, p_forms), 'review',
         format('Quote contains “%s” or a form of it', p_lemma),
         format('The quote does not contain “%s” or a recognisable form of it; a moderator will check it', p_lemma))
    || private.rule('plain_text', q !~* '(<[a-z/!][^>]*>|https?://|www\.)', 'review',
         null, 'The quote contains markup or a link; a moderator will check it');
  if y is not null and p_registered is not null then
    c := c || private.rule('antedating', y >= p_registered, 'review',
      format('Year is not before the sense is registered (%s)', p_registered),
      format('%s is earlier than the date the sense is registered from (%s): a possible antedating, checked by a moderator', y, p_registered));
  end if;
  if y is not null and p_obsolete is not null then
    c := c || private.rule('after_obsolete', y <= p_obsolete, 'review',
      null, format('The sense is recorded as obsolete by %s; a moderator will check this later use', p_obsolete));
  end if;
  return c;
end;
$$;

-- Per-contributor limits: 20 submissions a day, 10 waiting for review.
create function private.rate_checks(uid uuid)
returns jsonb
language sql
stable
set search_path = ''
as $$
  select
    private.rule('rate_day',
      (select count(*) from public.contributions k where k.contributor_id = uid and k.created_at > now() - interval '24 hours') < 20,
      'error', null, 'Limit reached: 20 contributions in 24 hours. Try again tomorrow.')
    || private.rule('rate_pending',
      (select count(*) from public.contributions k where k.contributor_id = uid and k.status = 'pending') < 10,
      'error', null, 'Limit reached: 10 contributions waiting for review. Try again once some are reviewed.')
$$;

-- Everything checked for a proposed usage. uid null (moderator re-check) skips the rate limits.
create function private.usage_report(u jsonb, uid uuid, p_exclude uuid)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  s public.senses;
  forms text[];
begin
  select * into s from public.senses where id = u ->> 'sense_id';
  if not found then
    return private.rule('sense_exists', false, 'error', null, 'Choose an existing sense to attest');
  end if;
  forms := array(select l.lemma from public.sense_lemmas l where l.sense_id = s.id) || s.lemma;
  return case when uid is null then '[]'::jsonb else private.rate_checks(uid) end
    || private.quote_checks(u, s.lemma, forms, s.date_earliest, s.obsolete_year, s.id, p_exclude)
    || private.source_checks(coalesce(u -> 'source', '{}'), case when jsonb_typeof(u -> 'year') = 'number' then (u ->> 'year')::integer end);
end;
$$;

-- Everything checked for a proposed sense. uid null (moderator re-check) skips the limits and the trust rule.
create function private.sense_report(p jsonb, uid uuid, p_exclude uuid)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  c jsonb := '[]';
  now_y integer := extract(year from now())::integer;
  v_lemma text := p ->> 'lemma';
  v_gloss text := p ->> 'gloss';
  v_pos text := p ->> 'pos';
  v_year integer := case when jsonb_typeof(p -> 'date_earliest') = 'number' then (p ->> 'date_earliest')::integer end;
  parents text[] := array(select jsonb_array_elements_text(coalesce(p -> 'parents', '[]')));
  missing text[];
  u jsonb := p -> 'usage';
  near record;
  accepted integer;
  rejected integer;
begin
  if uid is not null then
    c := c || private.rate_checks(uid);
  end if;
  c := c
    || private.rule('lemma', v_lemma ~ '^[[:alpha:]][[:alpha:][:digit:] ''’.-]{0,59}$', 'error',
         null, 'Word: up to 60 letters, spaces, hyphens or apostrophes')
    || private.rule('pos', v_pos = any (enum_range(null::public.part_of_speech)::text[]), 'error',
         null, 'Part of speech: noun, verb, adjective or adverb')
    || private.rule('shift', (p ->> 'shift') = any (enum_range(null::public.shift_type)::text[]), 'error',
         null, 'Shift type: choose one')
    || private.rule('source_type', (p ->> 'source_type') = any (enum_range(null::public.source_type)::text[]), 'error',
         null, 'Date source type: dictionary, corpus or citation')
    || private.rule('gloss_length', length(v_gloss) between 10 and 300, 'error',
         null, 'Gloss: a definition of 10 to 300 characters')
    || private.rule('examples',
         jsonb_array_length(coalesce(p -> 'examples', '[]')) <= 5
           and not exists (select 1 from jsonb_array_elements_text(coalesce(p -> 'examples', '[]')) e where length(e) > 200),
         'error', null, 'Examples: at most 5, each up to 200 characters')
    || private.rule('date_label', length(p ->> 'date_label') between 1 and 40, 'error',
         null, 'Date as recorded: required, at most 40 characters (e.g. 1965, c. 1300, 16th c.)')
    || private.rule('date_earliest', v_year between 600 and now_y, 'error',
         null, format('Earliest year: a whole year between 600 and %s', now_y))
    || private.rule('date_source', length(p ->> 'date_source') between 3 and 300, 'error',
         null, 'Date source: say where the date comes from (3 to 300 characters)')
    || private.rule('parents_count', cardinality(parents) <= 4, 'error', null, 'Parent senses: at most 4');

  select array_agg(x) into missing from unnest(parents) x where not exists (select 1 from public.senses s where s.id = x);
  c := c || private.rule('parents_exist', missing is null, 'error',
    case when cardinality(parents) > 0 then 'Parent senses exist' end,
    format('Unknown parent sense: %s', array_to_string(missing, ', ')));
  if (p ->> 'shift') = 'root' then
    c := c || private.rule('root_parents', cardinality(parents) = 0, 'error', null, 'A root sense has no parent senses; choose a shift type instead');
  elsif p ->> 'shift' is not null then
    c := c || private.rule('root_parents', cardinality(parents) > 0, 'error', null, 'Choose the parent sense this one grew from, or mark it as a root sense');
  end if;
  if missing is null and v_year is not null and cardinality(parents) > 0 then
    c := c || private.rule('parents_older',
      not exists (select 1 from public.senses s where s.id = any (parents) and s.date_earliest > v_year), 'review',
      'Parent senses are older than the proposed date',
      'A parent sense is registered after the proposed date; a moderator will check the lineage');
    c := c || private.rule('parents_same_word',
      not exists (select 1 from public.senses s where s.id = any (parents) and public.normalize_lemma(s.lemma) <> public.normalize_lemma(v_lemma)),
      'note', null, 'A parent sense belongs to another word');
  end if;

  if v_lemma is not null and v_pos = any (enum_range(null::public.part_of_speech)::text[]) and v_gloss is not null then
    c := c || private.rule('duplicate_gloss',
      not exists (
        select 1 from public.senses s
        where public.normalize_lemma(s.lemma) = public.normalize_lemma(v_lemma) and s.pos::text = v_pos
          and private.text_key(s.gloss) = private.text_key(v_gloss)
      ) and not exists (
        select 1 from public.contributions k
        where k.kind = 'sense' and k.status = 'pending' and k.id is distinct from p_exclude
          and public.normalize_lemma(k.lemma) = public.normalize_lemma(v_lemma) and k.payload ->> 'pos' = v_pos
          and private.text_key(k.payload ->> 'gloss') = private.text_key(v_gloss)
      ),
      'error', null, 'This gloss already exists, or is already proposed, for this word');
    select s.id, extensions.similarity(private.text_key(s.gloss), private.text_key(v_gloss)) as sim into near
    from public.senses s
    where public.normalize_lemma(s.lemma) = public.normalize_lemma(v_lemma) and s.pos::text = v_pos
    order by 2 desc
    limit 1;
    c := c || private.rule('similar_gloss', near.id is null or near.sim < 0.5, 'review',
      'Gloss differs from the existing senses',
      format('The gloss is close to %s; a moderator will check it is a new sense', near.id));
    c := c || private.rule('known_word',
      exists (select 1 from public.senses s where public.normalize_lemma(s.lemma) = public.normalize_lemma(v_lemma)), 'review',
      null, format('“%s” is a new head word; a moderator will check it', v_lemma));
  end if;

  if jsonb_typeof(u) = 'object' then
    c := c
      || private.quote_checks(u, v_lemma, array[v_lemma], v_year, null, null, p_exclude)
      || private.source_checks(coalesce(u -> 'source', '{}'), case when jsonb_typeof(u -> 'year') = 'number' then (u ->> 'year')::integer end);
  else
    c := c || private.rule('supporting_usage', false, 'review', null, 'No supporting usage: a moderator will check the sense against its date source');
  end if;

  if uid is not null then
    select count(*) filter (where status = 'accepted'), count(*) filter (where status = 'rejected')
      into accepted, rejected
    from public.contributions where contributor_id = uid;
    c := c || private.rule('trusted', accepted >= 3 and rejected = 0, 'review',
      'Contributor has 3 or more accepted contributions and none rejected',
      'New senses from contributors with fewer than 3 accepted contributions are reviewed by a moderator');
  end if;
  return c;
end;
$$;

-- ---------- Publishing ----------

create function private.contributor()
returns uuid
language plpgsql
stable
set search_path = ''
as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null then
    raise exception 'Sign in to contribute' using errcode = '42501';
  end if;
  if coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) then
    raise exception 'Sign in with an email address to contribute' using errcode = '42501';
  end if;
  return uid;
end;
$$;

create function private.is_moderator(uid uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (select 1 from public.moderators m where m.user_id = uid)
$$;

-- Next free id for a lemma and part of speech: cloud.n.07, ice_cream.n.01.
create function private.next_sense_id(p_lemma text, p_pos public.part_of_speech)
returns text
language plpgsql
volatile
set search_path = ''
as $$
declare
  k text := lower(regexp_replace(btrim(p_lemma), '\s+', '_', 'g')) || '.'
    || case p_pos when 'noun' then 'n' when 'verb' then 'v' when 'adjective' then 'adj' else 'adv' end || '.';
  n integer;
begin
  perform pg_advisory_xact_lock(hashtext('shiftnet.sense_id:' || k));
  select coalesce(max(private.to_int(substr(id, length(k) + 1))), 0) + 1 into n
  from public.senses where left(id, length(k)) = k;
  return k || lpad(n::text, 2, '0');
end;
$$;

-- Reuse a cited work with the same URL, else the same identifier, else (with neither) the same kind, title and author.
create function private.source_for(s jsonb)
returns uuid
language plpgsql
volatile
set search_path = ''
as $$
declare
  sid uuid;
begin
  select src.id into sid
  from public.sources src
  where (s ->> 'url' is not null and lower(src.url) = lower(s ->> 'url'))
     or (s ->> 'identifier' is not null and lower(src.identifier) = lower(s ->> 'identifier'))
     or (s ->> 'url' is null and s ->> 'identifier' is null
         and src.kind::text = s ->> 'kind'
         and public.normalize_lemma(src.title) = public.normalize_lemma(s ->> 'title')
         and coalesce(public.normalize_lemma(src.author), '') = coalesce(public.normalize_lemma(s ->> 'author'), ''))
  order by (s ->> 'url' is not null and lower(src.url) = lower(s ->> 'url')) desc, src.created_at
  limit 1;
  if sid is null then
    insert into public.sources (kind, title, author, publisher, published_label, published_year, url, identifier, accessed_on)
    values (
      (s ->> 'kind')::public.reference_kind, s ->> 'title', s ->> 'author', s ->> 'publisher', s ->> 'published_label',
      (s ->> 'published_year')::integer, s ->> 'url', s ->> 'identifier', (s ->> 'accessed_on')::date
    )
    returning id into sid;
  end if;
  return sid;
end;
$$;

-- Write an accepted contribution into the lexicon and mark it accepted.
create function private.publish(r public.contributions, m public.validation_method, reviewer uuid, note text)
returns public.contributions
language plpgsql
volatile
set search_path = ''
as $$
declare
  p jsonb := r.payload;
  u jsonb;
  sid text;
  att uuid;
begin
  if r.kind = 'usage' then
    sid := r.sense_id;
    u := p;
  else
    sid := private.next_sense_id(p ->> 'lemma', (p ->> 'pos')::public.part_of_speech);
    insert into public.senses (id, lemma, pos, gloss, examples, date_label, date_earliest, shift, source, source_type, validation)
    values (
      sid, p ->> 'lemma', (p ->> 'pos')::public.part_of_speech, p ->> 'gloss',
      array(select jsonb_array_elements_text(coalesce(p -> 'examples', '[]'))),
      p ->> 'date_label', (p ->> 'date_earliest')::integer, (p ->> 'shift')::public.shift_type,
      p ->> 'date_source', (p ->> 'source_type')::public.source_type, m
    );
    insert into public.sense_parents (sense_id, parent_id, position)
    select sid, e, (o - 1)::smallint
    from jsonb_array_elements_text(coalesce(p -> 'parents', '[]')) with ordinality t(e, o);
    insert into public.sense_lemmas (sense_id, lemma, position) values (sid, p ->> 'lemma', 0);
    u := p -> 'usage';
  end if;

  if jsonb_typeof(u) = 'object' then
    insert into public.attestations (sense_id, source_id, quote, year, date_label, locator, validation, validated_at)
    values (sid, private.source_for(u -> 'source'), u ->> 'quote', (u ->> 'year')::integer, u ->> 'date_label', u ->> 'locator', m, now())
    returning id into att;
  end if;

  update public.contributions
  set status = 'accepted', validation = m, sense_id = sid, attestation_id = att,
    reviewer_id = reviewer, review_note = note, decided_at = now()
  where id = r.id
  returning * into r;
  return r;
end;
$$;

-- ---------- RPCs ----------

-- Run the automatic checks without submitting, for the form's "Check" button.
create function public.check_usage(p jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  return private.usage_report(private.clean_usage(p), private.contributor(), null);
end;
$$;

create function public.check_sense(p jsonb)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  return private.sense_report(private.clean_sense(p), private.contributor(), null);
end;
$$;

-- Propose a usage: {sense_id, quote, year, date_label?, locator?, source: {kind, title, author?, publisher?,
-- published_label?, published_year?, url?, identifier?, accessed_on?}}.
create function public.submit_usage(p jsonb)
returns public.contributions
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  uid uuid := private.contributor();
  u jsonb := private.clean_usage(p);
  c jsonb;
  r public.contributions;
begin
  perform pg_advisory_xact_lock(hashtext('shiftnet.contributor:' || uid::text));
  c := private.usage_report(u, uid, null);
  perform private.raise_on_errors(c);
  insert into public.contributions (contributor_id, kind, lemma, sense_id, payload, checks)
  select uid, 'usage', s.lemma, s.id, u, c from public.senses s where s.id = u ->> 'sense_id'
  returning * into r;
  if not private.has_level(c, 'review') then
    r := private.publish(r, 'automatic', null, null);
  end if;
  return r;
end;
$$;

-- Propose a sense: {lemma, pos, gloss, examples[], date_label, date_earliest, shift, date_source,
-- source_type, parents[], usage?: {quote, year, date_label?, locator?, source}}.
create function public.submit_sense(p jsonb)
returns public.contributions
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  uid uuid := private.contributor();
  s jsonb := private.clean_sense(p);
  c jsonb;
  r public.contributions;
begin
  perform pg_advisory_xact_lock(hashtext('shiftnet.contributor:' || uid::text));
  c := private.sense_report(s, uid, null);
  perform private.raise_on_errors(c);
  insert into public.contributions (contributor_id, kind, lemma, payload, checks)
  values (uid, 'sense', s ->> 'lemma', s, c)
  returning * into r;
  if not private.has_level(c, 'review') then
    r := private.publish(r, 'automatic', null, null);
  end if;
  return r;
end;
$$;

-- Moderators: accept or reject a pending contribution, or confirm / withdraw an auto-accepted one.
-- Accepting re-runs the blocking checks (the lexicon may have changed since submission).
create function public.review_contribution(p_id uuid, p_decision text, p_note text default null)
returns public.contributions
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  uid uuid := private.contributor();
  note text := private.clean(p_note);
  r public.contributions;
  c jsonb;
begin
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
  if not found then
    raise exception 'Contribution not found' using errcode = 'P0002';
  end if;
  if r.contributor_id = uid then
    raise exception 'Another moderator must review your own contributions' using errcode = '42501';
  end if;
  if p_decision = 'reject' and note is null then
    raise exception 'Say why the contribution is rejected; the contributor sees the note' using errcode = '22023';
  end if;

  if r.status = 'pending' and p_decision = 'accept' then
    c := case r.kind when 'usage' then private.usage_report(r.payload, null, r.id) else private.sense_report(r.payload, null, r.id) end;
    perform private.raise_on_errors(c);
    update public.contributions set checks = c where id = r.id returning * into r;
    r := private.publish(r, 'manual', uid, note);
  elsif r.status = 'pending' then
    update public.contributions
    set status = 'rejected', reviewer_id = uid, review_note = note, decided_at = now()
    where id = r.id returning * into r;
  elsif r.status = 'accepted' and r.validation = 'automatic' and p_decision = 'accept' then
    update public.attestations set validation = 'manual', validated_at = now() where id = r.attestation_id;
    if r.kind = 'sense' then
      update public.senses set validation = 'manual' where id = r.sense_id;
    end if;
    update public.contributions
    set validation = 'manual', reviewer_id = uid, review_note = note, decided_at = now()
    where id = r.id returning * into r;
  elsif r.status = 'accepted' and r.validation = 'automatic' then
    -- Withdraw from the lexicon. A sense others have built on stays; edit it with a privileged connection.
    if r.kind = 'sense' and (
      exists (select 1 from public.sense_parents sp where sp.parent_id = r.sense_id)
      or exists (select 1 from public.attestations a where a.sense_id = r.sense_id and a.id is distinct from r.attestation_id)
      or exists (select 1 from public.contributions k where k.sense_id = r.sense_id and k.id <> r.id and k.status <> 'rejected')
    ) then
      raise exception 'Other senses or usages depend on this sense; it cannot be withdrawn here' using errcode = '55000';
    end if;
    delete from public.attestations where id = r.attestation_id;
    if r.kind = 'sense' then
      delete from public.senses where id = r.sense_id;
    end if;
    update public.contributions
    set status = 'rejected', validation = null, attestation_id = null,
      sense_id = case when r.kind = 'sense' then null else r.sense_id end,
      reviewer_id = uid, review_note = note, decided_at = now()
    where id = r.id returning * into r;
  else
    raise exception 'This contribution has already been reviewed' using errcode = '55000';
  end if;
  return r;
end;
$$;

create function public.is_moderator()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select private.is_moderator(auth.uid())
$$;

-- ---------- Access ----------
-- Contributors read their own contributions, moderators read all; nobody writes except through the RPCs.
-- Pending contributions are never visible to anon.

alter table public.moderators enable row level security;
alter table public.contributions enable row level security;

create policy "Users can see whether they are a moderator" on public.moderators
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "Contributors can read their own contributions" on public.contributions
  for select to authenticated using ((select auth.uid()) = contributor_id);
create policy "Moderators can read all contributions" on public.contributions
  for select to authenticated using (exists (select 1 from public.moderators m where m.user_id = (select auth.uid())));

revoke all on public.moderators, public.contributions from anon, authenticated;
grant select on public.moderators, public.contributions to authenticated;

revoke execute on all functions in schema private from public, anon, authenticated;
revoke execute on function
  public.check_usage(jsonb),
  public.check_sense(jsonb),
  public.submit_usage(jsonb),
  public.submit_sense(jsonb),
  public.review_contribution(uuid, text, text),
  public.is_moderator()
  from public, anon;
grant execute on function
  public.check_usage(jsonb),
  public.check_sense(jsonb),
  public.submit_usage(jsonb),
  public.submit_sense(jsonb),
  public.review_contribution(uuid, text, text),
  public.is_moderator()
  to authenticated;
