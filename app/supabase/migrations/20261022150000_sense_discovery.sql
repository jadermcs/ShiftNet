-- Sense discovery: usages of a lemma sampled from a web corpus (fineweb-edu), encoded with a
-- contextual word encoder (LexSPLADE) and clustered. Each cluster is a candidate sense that the
-- ShiftNet team reviews: match it to an existing sense, promote it to a new sense, or reject it.
--
-- Written by the backend (backend/, privileged connection). Staging data only: nothing here is
-- readable through the Data API; reviewed results reach the public through senses / attestations.

create type public.candidate_status as enum ('pending', 'matched', 'promoted', 'rejected');

-- One clustering of one lemma's usages.
create table public.discovery_runs (
  id uuid primary key default gen_random_uuid(),
  lemma text not null,
  forms text[] not null,                     -- surface forms searched for: cloud, clouds
  corpus text not null,                      -- e.g. HuggingFaceFW/fineweb-edu
  dumps text[] not null default '{}',        -- crawl snapshots sampled, e.g. CC-MAIN-2013-20
  model text not null,                       -- encoder id
  params jsonb not null default '{}',        -- thresholds, quotas, seed
  usage_count integer not null default 0,
  noise_count integer not null default 0,    -- usages left out of every cluster
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint discovery_runs_lemma_not_blank check (length(trim(lemma)) > 0),
  constraint discovery_runs_forms_not_empty check (cardinality(forms) > 0)
);

create index discovery_runs_lemma_idx on public.discovery_runs (public.normalize_lemma(lemma), started_at desc);

-- One cluster of usages: a candidate sense.
create table public.sense_candidates (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.discovery_runs (id) on delete cascade,
  cluster integer not null,                  -- cluster number within the run, largest first
  lemma text not null,
  size integer not null,
  terms jsonb not null default '[]',         -- [{term, weight}]: strongest dimensions of the centroid
  first_seen date,                           -- earliest crawl date among its usages
  last_seen date,
  year_counts jsonb not null default '{}',   -- {"2013": 41, "2024": 7}: usages per crawl year
  nearest_sense_id text references public.senses (id) on delete set null, -- closest existing sense
  nearest_score real,                        -- cosine similarity to it, 0–1
  status public.candidate_status not null default 'pending',
  sense_id text references public.senses (id) on delete set null, -- sense matched or created on review
  review_note text,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  constraint sense_candidates_cluster_key unique (run_id, cluster),
  constraint sense_candidates_size_positive check (size > 0),
  constraint sense_candidates_decided check ((status = 'pending') = (decided_at is null)),
  constraint sense_candidates_sense_when_kept check (status not in ('matched', 'promoted') or sense_id is not null)
);

create index sense_candidates_queue_idx on public.sense_candidates (public.normalize_lemma(lemma), created_at desc)
  where status = 'pending';
create index sense_candidates_nearest_idx on public.sense_candidates (nearest_sense_id);
create index sense_candidates_sense_idx on public.sense_candidates (sense_id);

-- One occurrence of the lemma in a corpus document.
create table public.corpus_usages (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.discovery_runs (id) on delete cascade,
  candidate_id uuid references public.sense_candidates (id) on delete set null, -- null: noise
  doc_id text not null,                      -- corpus document id
  dump text,                                 -- crawl snapshot
  url text,
  crawled_on date,
  context text not null,                     -- the window that was encoded, without markers
  target_start integer not null,             -- character span of the target word in context
  target_end integer not null,
  similarity real,                           -- cosine to its cluster centroid; higher = more typical
  terms jsonb not null default '[]',         -- [{term, weight}]: strongest dimensions of the usage
  attestation_id uuid references public.attestations (id) on delete set null, -- once quoted in the lexicon
  constraint corpus_usages_span check (target_start >= 0 and target_end > target_start and target_end <= length(context)),
  constraint corpus_usages_once unique (run_id, doc_id, context, target_start)
);

create index corpus_usages_candidate_idx on public.corpus_usages (candidate_id, similarity desc nulls last);
create index corpus_usages_run_idx on public.corpus_usages (run_id);
create index corpus_usages_attestation_idx on public.corpus_usages (attestation_id);

-- Staging data: RLS on with no policies, and no grants, so only privileged roles see it.
alter table public.discovery_runs enable row level security;
alter table public.sense_candidates enable row level security;
alter table public.corpus_usages enable row level security;

revoke all on public.discovery_runs, public.sense_candidates, public.corpus_usages from anon, authenticated;
