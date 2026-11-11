-- ShiftNet schema (SQLite). Created by db.init(); see db.py for the SQL functions it relies on:
-- normalize_lemma(t) (lower case, trimmed, accents removed) is registered on every connection.
--
-- Conventions: ids are text (sense ids such as cloud.n.02, UUIDs elsewhere); arrays and objects are
-- JSON text in columns declared JSON; dates are ISO 'YYYY-MM-DD' (DATE), timestamps ISO 8601 UTC.
-- sense_num / branch and attestation relevance are kept up to date by db.renumber_senses() and
-- db.refresh_relevance(), which every writer in the backend calls.

pragma foreign_keys = on;

-- ---------- Lexicon ----------

create table if not exists synsets (
  id text primary key,
  pos text not null check (pos in ('noun', 'verb', 'adjective', 'adverb')),
  lemmas JSON not null check (json_array_length(lemmas) > 0),  -- members; the first one names the synset
  gloss text
);

create table if not exists synset_hypernyms (
  synset_id text not null references synsets (id) on delete cascade,
  hypernym_id text not null references synsets (id) on delete cascade,
  position integer not null default 0,         -- 0 = the path shown in breadcrumbs; >0 = also under
  primary key (synset_id, hypernym_id),
  check (synset_id <> hypernym_id)
);

create index if not exists synset_hypernyms_hypernym_idx on synset_hypernyms (hypernym_id);

create table if not exists senses (
  id text primary key,                          -- stable id used in URLs, e.g. cloud.n.02
  lemma text not null,
  lemma_key text generated always as (normalize_lemma(lemma)) stored,
  pos text not null check (pos in ('noun', 'verb', 'adjective', 'adverb')),
  gloss text not null,
  examples JSON not null default '[]',
  date_label text not null,                     -- as recorded: '1965', 'c. 1300', '16th c.'
  date_earliest integer not null,               -- earliest possible year; rows sort on this
  obsolete_year integer,
  obsolete_label text,
  shift text not null default 'root'
    check (shift in ('root', 'broadening', 'narrowing', 'metaphor', 'metonymy', 'amelioration', 'pejoration', 'other')),
  source text not null,                         -- provenance of the date
  source_type text not null check (source_type in ('dictionary', 'corpus', 'citation')),
  sense_num integer,                            -- n. 1, n. 2 … per lemma and pos (db.renumber_senses)
  branch integer,                               -- 0–7, registration order within the lemma
  validation text not null default 'editorial' check (validation in ('editorial', 'automatic', 'manual')),
  synset_id text references synsets (id) on delete set null,
  created_at TIMESTAMP not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  check (obsolete_year is null or obsolete_year >= date_earliest)
);

create index if not exists senses_lemma_idx on senses (lemma, date_earliest, id);
create index if not exists senses_lemma_key_idx on senses (lemma_key);
create index if not exists senses_timeline_idx on senses (date_earliest desc, id);
create index if not exists senses_synset_idx on senses (synset_id);

create table if not exists sense_parents (
  sense_id text not null references senses (id) on delete cascade,
  parent_id text not null references senses (id) on delete cascade,
  position integer not null default 0,          -- 0 = the branch the sense grows from; >0 = merged parents
  source text,
  primary key (sense_id, parent_id),
  check (sense_id <> parent_id)
);

create index if not exists sense_parents_parent_idx on sense_parents (parent_id);

-- Synset members (synonyms), including multi-word expressions such as "cloud computing".
create table if not exists sense_lemmas (
  sense_id text not null references senses (id) on delete cascade,
  lemma text not null,
  lemma_key text generated always as (normalize_lemma(lemma)) stored,
  position integer not null default 0,
  primary key (sense_id, lemma)
);

create index if not exists sense_lemmas_key_idx on sense_lemmas (lemma_key);

create table if not exists relations (
  sense_id text not null references senses (id) on delete cascade,
  type text not null check (type in ('antonym', 'hypernym', 'hyponym', 'meronym', 'holonym', 'derived')),
  target_lemma text not null,
  position integer not null default 0,
  primary key (sense_id, type, target_lemma)
);

-- A cited work, shared by every attestation quoted from it.
create table if not exists sources (
  id text primary key default (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
    || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  kind text not null
    check (kind in ('book', 'website', 'article', 'journal', 'newspaper', 'dictionary', 'corpus', 'archive', 'other')),
  title text not null check (length(trim(title)) > 0),
  author text,
  publisher text,
  published_label text,
  published_year integer,
  url text check (url is null or lower(substr(url, 1, 7)) = 'http://' or lower(substr(url, 1, 8)) = 'https://'),
  identifier text,                              -- ISBN, DOI, archive shelfmark …
  accessed_on DATE,
  created_at TIMESTAMP not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

create table if not exists attestations (
  id text primary key default (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
    || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  sense_id text not null references senses (id) on delete cascade,
  source_id text not null references sources (id) on delete restrict,
  quote text not null check (length(trim(quote)) > 0),
  year integer,
  date_label text,
  locator text,
  relevance_override real check (relevance_override is null or relevance_override between 0 and 1),
  relevance real not null default 0,            -- db.refresh_relevance, 0–1; higher shows first
  validation text not null default 'editorial' check (validation in ('editorial', 'automatic', 'manual')),
  validated_at TIMESTAMP,
  created_at TIMESTAMP not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

create index if not exists attestations_sense_rank_idx on attestations (sense_id, relevance desc, year);
create index if not exists attestations_source_idx on attestations (source_id);

-- ---------- Contributions (single local user, who is also the moderator) ----------

create table if not exists contributions (
  id text primary key default (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
    || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  contributor_id text not null default 'local',
  kind text not null check (kind in ('usage', 'sense', 'relation')),
  status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
  lemma text not null,
  sense_id text references senses (id) on delete set null,
  attestation_id text references attestations (id) on delete set null,
  payload JSON not null,                        -- the normalised proposal (contributions.clean_*)
  checks JSON not null default '[]',            -- [{code, level, message}] from the latest run of the checks
  validation text check (validation in ('automatic', 'manual')),
  reviewer_id text,
  review_note text check (review_note is null or length(review_note) <= 1000),
  published JSON,                               -- for a relation: what was written, so it can be withdrawn
  decided_at TIMESTAMP,
  created_at TIMESTAMP not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  check ((status = 'accepted') = (validation is not null))
);

create index if not exists contributions_created_idx on contributions (created_at desc);
create index if not exists contributions_queue_idx on contributions (created_at) where status = 'pending';
create index if not exists contributions_sense_idx on contributions (sense_id);

-- ---------- Sense discovery (staging; reviewed results reach senses / attestations) ----------

create table if not exists discovery_runs (
  id text primary key default (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
    || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  lemma text not null check (length(trim(lemma)) > 0),
  lemma_key text generated always as (normalize_lemma(lemma)) stored,
  forms JSON not null check (json_array_length(forms) > 0),
  corpus text not null,
  dumps JSON not null default '[]',
  model text not null,
  params JSON not null default '{}',
  bulk_tag text generated always as (params ->> 'bulk') stored,
  usage_count integer not null default 0,
  noise_count integer not null default 0,
  started_at TIMESTAMP not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  finished_at TIMESTAMP
);

create index if not exists discovery_runs_lemma_idx on discovery_runs (lemma_key, started_at desc);
create index if not exists discovery_runs_bulk_idx on discovery_runs (bulk_tag) where bulk_tag is not null;
-- Covering index for the Discovery word list (usages per word).
create index if not exists discovery_runs_usage_idx on discovery_runs (lemma_key, usage_count);

create table if not exists sense_candidates (
  id text primary key default (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
    || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  run_id text not null references discovery_runs (id) on delete cascade,
  cluster integer not null,
  lemma text not null,
  lemma_key text generated always as (normalize_lemma(lemma)) stored,
  size integer not null check (size > 0),
  terms JSON not null default '[]',             -- [{term, weight}]
  first_seen DATE,
  last_seen DATE,
  year_counts JSON not null default '{}',
  nearest_sense_id text references senses (id) on delete set null,
  nearest_score real,
  status text not null default 'pending' check (status in ('pending', 'matched', 'promoted', 'rejected')),
  sense_id text references senses (id) on delete set null,
  review_note text,
  decided_at TIMESTAMP,
  created_at TIMESTAMP not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  unique (run_id, cluster),
  check ((status = 'pending') = (decided_at is null)),
  check (status not in ('matched', 'promoted') or sense_id is not null)
);

create index if not exists sense_candidates_queue_idx on sense_candidates (lemma_key, created_at desc) where status = 'pending';
create index if not exists sense_candidates_nearest_idx on sense_candidates (nearest_sense_id);
create index if not exists sense_candidates_sense_idx on sense_candidates (sense_id);
-- Covering index for the Discovery word list (candidates per word and status, crawl span).
create index if not exists sense_candidates_lemma_idx on sense_candidates (lemma_key, status, first_seen, last_seen);

create table if not exists corpus_usages (
  id text primary key default (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
    || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  run_id text not null references discovery_runs (id) on delete cascade,
  candidate_id text references sense_candidates (id) on delete set null,  -- null: noise
  doc_id text not null,
  dump text,
  url text,
  crawled_on DATE,
  context text not null,
  target_start integer not null,
  target_end integer not null,
  similarity real,
  terms JSON not null default '[]',
  attestation_id text references attestations (id) on delete set null,
  check (target_start >= 0 and target_end > target_start and target_end <= length(context))
);

-- One row per occurrence (run, document, position, context); save_run skips repeats.
create unique index if not exists corpus_usages_once on corpus_usages (run_id, doc_id, target_start, context);
create index if not exists corpus_usages_candidate_idx on corpus_usages (candidate_id, similarity desc);
create index if not exists corpus_usages_attestation_idx on corpus_usages (attestation_id) where attestation_id is not null;

-- ---------- Relation suggestions (LexSPLADE) ----------

create table if not exists relation_suggestions (
  id text primary key default (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
    || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  sense_id text not null references senses (id) on delete cascade,
  type text not null check (type in ('synonym', 'hypernym', 'hyponym', 'meronym', 'holonym')),
  target_lemma text not null check (length(trim(target_lemma)) > 0),
  target_key text generated always as (normalize_lemma(target_lemma)) stored,
  target_sense_id text references senses (id) on delete set null,
  target_synset_id text references synsets (id) on delete set null,
  target_score real,
  score real not null check (score between 0 and 1),  -- the checks treat 0.6 or more as support
  evidence JSON not null default '{}',
  model text not null,
  created_at TIMESTAMP not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

create unique index if not exists relation_suggestions_key on relation_suggestions (sense_id, type, target_key);
create index if not exists relation_suggestions_rank_idx on relation_suggestions (sense_id, score desc);
create index if not exists relation_suggestions_target_idx on relation_suggestions (target_sense_id);
