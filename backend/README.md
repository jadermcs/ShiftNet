# ShiftNet backend

The ShiftNet database and the tools around it. The database is one SQLite file: `$SHIFTNET_DB`, by default `~/data/shiftnet.sqlite` (schema: `src/shiftnet_backend/schema.sql`, created on first use).

- **API** (`api.py`, `contributions.py`): `shiftnet serve`, the HTTP API the web app (`../app`) reads and writes through, including the contribution checks and the review queue. There is one local user, who contributes and reviews.
- **Models** (`models.py`, `lexicon.py`): typed rows (Pydantic) for senses, parent links, synonyms, relations, sources and attestations, committed in one transaction per batch. The checks mirror the database constraints, so bad rows fail before they reach the database.
- **Sense discovery** (`discovery/`): samples a word's usages from [fineweb-edu](https://huggingface.co/datasets/HuggingFaceFW/fineweb-edu), encodes each with [LexSPLADE](https://huggingface.co/jadermcs/lexsplade-bert-large-silver), clusters them into candidate senses, and stores the candidates for review.
- **Relation suggestions** (`discovery/relations.py`): proposes WordNet relations (synonym, hypernym, hyponym, meronym, holonym) for each sense with the same encoder. Contributors pick them up on the Contribute page.
- **MCP server** (`mcp_server.py`): lets an assistant (Claude Code, Claude Desktop …) browse the lexicon and review candidates: match, promote with a gloss, or reject.

## Setup

```sh
cd backend
uv sync --all-extras          # Python 3.12, CUDA 13.0 torch (pyproject: pytorch-cu130 index); drop --all-extras for the API, models and CLI only
uv run shiftnet seed          # once, into an empty database: the sample lexicon (seed/seed.sql)
uv run shiftnet serve         # the API for the web app: http://127.0.0.1:8000/api/…
```

Every command takes `--db PATH` instead of `$SHIFTNET_DB`. `shiftnet serve --static ../app/dist` also serves the built web app, so one process runs everything. SQLite runs in WAL mode, so the API keeps serving while a CLI command writes; writers queue for the lock.

The sample lexicon comes from `seed/generate_seed.py` (`python3 seed/generate_seed.py > seed/seed.sql`).

## Committing data

```sh
uv run shiftnet import senses.jsonl            # one sense per line, or a JSON list
uv run shiftnet import senses.jsonl --dry-run  # validate and write, then roll back
```

```json
{"lemma": "cloud", "pos": "noun", "gloss": "remote servers reached over the internet",
 "date_label": "1990s", "date_earliest": 1990, "shift": "metaphor",
 "source": "Computing trade press", "source_type": "corpus",
 "parents": [{"parent_id": "cloud.n.02", "source": "OED"}],
 "synonyms": ["cloud computing"], "relations": [{"type": "hypernym", "target_lemma": "network"}],
 "attestations": [{"quote": "Back up your photos to the cloud.", "year": 2009,
                   "source": {"kind": "website", "title": "example.org", "url": "https://example.org/a"}}]}
```

Without `id`, a sense gets the next free id (`cloud.n.07`) using the same rule and lock as community contributions. With an existing `id`, it is updated: parents, synonyms and relations are replaced, and attestations are added. A root sense has no parents and every other shift type needs at least one. In Python:

```python
from shiftnet_backend import db, lexicon
from shiftnet_backend.models import SenseIn

with db.transaction() as conn:
    lexicon.save_senses(conn, [SenseIn(...)])
```

## Sense discovery

```sh
uv run shiftnet -v discover cloud                      # 200 usages × 8 snapshots, 2013 → 2025, streamed from the Hub
uv run shiftnet discover troll --forms troll trolls trolling trolled --per-dump 100
uv run shiftnet discover cloud --dumps CC-MAIN-2013-20 --data-files 'CC-MAIN-2013-20=/data/fineweb-edu/CC-MAIN-2013-20/*.parquet'

uv run shiftnet candidates --lemma cloud               # pending clusters, nearest existing sense
uv run shiftnet show <candidate-id>                    # terms, crawl years, typical and borderline usages
uv run shiftnet match <candidate-id> [--sense cloud.n.02]
uv run shiftnet promote <candidate-id> --pos noun --gloss "…" --parent cloud.n.06 --shift narrowing
uv run shiftnet reject <candidate-id> --note "proper name"
```

How a run works:

1. **Sample.** It streams each fineweb-edu snapshot (one config per Common Crawl dump), keeps documents that contain one of the forms (whole word, case-insensitive), and takes the sentence around each match, at most 2 per document. That gives `--per-dump` usages from each snapshot, each with its crawl date and URL.
2. **Encode.** It wraps the target in `<t>…</t>` (no spaces inside, which RoBERTa's byte-level BPE needs) and encodes it with LexSPLADE. The model's limit is **64 tokens**, so sentences are trimmed around the target first; otherwise the markers would be cut off and the model would silently return a sentence embedding. Each usage becomes a sparse vector over the BERT vocabulary, so it can be read as words (river bank → *side, water, edge, shore*).
3. **Cluster.** It runs average-linkage agglomerative clustering on cosine distance, cut where the average similarity drops below `--threshold` (default 0.35). Same-sense pairs score about 0.6–0.9 and different senses about 0.1–0.2. Clusters smaller than `--min-size` are dropped, and their usages join the nearest kept cluster if they are similar enough.
4. **Describe.** Each cluster gets its strongest centroid terms (the target's own forms are left out), its first and last crawl dates, usages per year, and the closest sense already in the lexicon. That last one comes from encoding the senses' examples and attestation quotes the same way.

Everything is stored in `discovery_runs`, `sense_candidates` and `corpus_usages`. These tables are not readable by `anon` or `authenticated`.

Reviewing:

- **match** quotes the cluster's most typical usages as attestations of the existing sense.
- **promote** creates the sense (`validation = 'automatic'` by default, `source_type = 'corpus'`), copies 2 usages into its examples, quotes 3 as attestations citing the web page, and records which crawl it was first seen in.
- **reject** records the decision only.

**About dates.** fineweb-edu starts in 2013, and a crawl date only shows a usage existed *by then*. A promoted sense is dated by its first crawl year unless you pass `--date-label` and `--date-earliest`. Comparing year counts across snapshots is how a recent sense shows up. For older senses, match them rather than promote.

**Cost.** On CPU (8 cores) the encoder handles about 18 usages/s, so 8 × 200 usages take a few minutes, plus streaming time. Clustering is O(n²) in memory and is capped at 6,000 usages per run. Use `--device cuda` on a GPU.

## Bulk sense discovery

`discover` handles one word. `shiftnet bulk` runs the same method for the N most frequent content lemmas of fineweb-edu at once. It is split into stages that read and write one work directory. Each stage can be re-run, and `encode` and `cluster` resume where they stopped.

```sh
W=/data/shiftnet-bulk
uv run shiftnet -v bulk download --workdir $W --docs 500000      # first shards of the 8 default snapshots (~20 GB)
uv run shiftnet -v bulk count    --workdir $W                    # pass 1: every word form, per snapshot
uv run shiftnet -v bulk vocab    --workdir $W --top 20000        # lemmatise, keep the 20k most frequent content lemmas
uv run shiftnet -v bulk sample   --workdir $W --per-lemma 2000   # pass 2: 250 usages per lemma and snapshot
for i in 0 1 2 3; do                                             # one process per GPU
  CUDA_VISIBLE_DEVICES=$i uv run shiftnet -v bulk encode --workdir $W --shard $i --shards 4 \
    --device cuda --dtype bfloat16 --batch-size 512 &
done; wait
uv run shiftnet -v bulk cluster  --workdir $W                    # resolve ambiguous forms, cluster each lemma
uv run shiftnet -v bulk import --workdir $W                      # into discovery_runs / sense_candidates
uv run shiftnet bulk status --workdir $W                         # what each stage has produced
```

How it works:

1. **Count.** Both corpus passes read local parquet row groups in parallel. A document costs one regex `findall` plus a set intersection with the vocabulary; no Python code runs per word.
2. **Lemmatise** (`lemmatize.py`), once per word type, not per token. WordNet's morphy covers dictionary words and irregular forms. For everything else (*selfies*, *doomscrolling*), suffix rules are **learnt from the corpus**: each pair morphy can reduce gives a rule (*running → run*: strip `ning`), and a rule needs 20 supporting types. An unknown form takes the rule whose output is the most frequent attested word. On 50k documents it learns `s`, `ing`, `ed`, `ing→e`, `ies→y`, consonant doubling, `a→um`, `i→us` and so on. Function words, numbers, non-ASCII words and lemmas capitalised more than half the time (names) are left out. `--dictionary-only` keeps WordNet lemmas only, which also drops neologisms.
3. **Ambiguous forms** (*leaves*: leaf | leave; *saw*: saw | see; *left*: left | leave) are offered to every candidate lemma. The other lemmas of a chosen lemma's ambiguous forms (*seed*, a rival of *see*) are added to the vocabulary as *competitors*, so they have usages of their own. After encoding, each usage goes to the lemma whose centroid of *unambiguous* usages it is closest to: *leaves* next to branches goes to *leaf*, next to the office to *leave*. A lemma with fewer than 20 unambiguous usages cannot win, so *running* (noun) goes to *run*.
4. **Sample.** From the counts, every lemma has a keep probability per snapshot that meets its quota on average, so sampling is one pass. Only kept occurrences are cut out (their sentence) and tokenised, in one batched call with offsets, then trimmed to 64 tokens at word boundaries. Each lemma keeps at most 2 usages per document and no repeated context. Usages are stored as memory-mapped Arrow files in `usages/`.
5. **Encode.** Each GPU process takes a contiguous slice and writes fixed-width top-128 vectors (`uint16` index + `float16` weight, 512 bytes a usage) to memory-mapped `.npy` files, checkpointing every 4k usages. LexSPLADE uses about 225 dimensions per usage, and the top 128 move cosine similarities by at most 0.03. 20k lemmas × 2,000 usages is about 40M usages and 20 GB.
6. **Cluster.** Average linkage as in `discover` (scipy's nearest-neighbour chain), one process per core. `--min-size` defaults to 10 here. Lemmas with fewer than 50 usages are skipped. Each candidate stores its 15 most typical and 5 most borderline usages. The rest are counted (`usage_count`, `noise_count`) but not stored, so the database gets about 20 usages per candidate instead of 40M rows. Results go to `runs/*.jsonl.gz`.
7. **Import** skips lemmas already imported under the same `--tag` (default: the work directory's name). For lemmas already in the lexicon, it encodes the existing senses' examples to record each candidate's nearest sense, as `discover` does.

**Cost.** Counting runs at about 0.4M tokens/s per core: 500k documents × 8 snapshots ≈ 4B tokens, so about 10 minutes on 16 cores. Encoding is the bottleneck. On 8 CPU cores it runs at about 3 usages/s, because real contexts fill most of the 64 tokens. Measured on one RTX 5060 Ti (16 GB) with `lexsplade-roberta-large-silver-wic-wnbags` in bfloat16: about 1,000 usages/s, so 37.6M usages took about 11 hours; expect roughly 2–4k/s per A100. Clustering 18k lemmas took 36 minutes on 20 cores. `sample` spools each batch to disk and peaks at about 12 GB of RAM with 10 workers (`--workers`); run it under a memory cap (`systemd-run --user --scope -p MemoryMax=18G …`) on a shared machine. Plan on 60 GB of disk.

## Relation suggestions

```sh
uv run shiftnet relations suggest mouse cloud      # or no words: every sense (about 4 s per sense on CPU)
uv run shiftnet relations show mouse.n.01
```

LexSPLADE reads a marked word as a weighted list of vocabulary terms. Two readings of that list give relations:

- **Synonyms:** the sense's own vector, built from its gloss, examples and best quotes with the word marked, lists words that could stand in its place. A candidate is kept if putting it back into those contexts gives a similar vector. This can't tell a synonym from a sister term (mouse → rat, cat), so synonym proposals always go to a moderator.
- **Hypernyms and meronyms:** a `[MASK]` slot in a pattern that carries the gloss ("a mouse (a small rodent …) is a kind of <t> [MASK] </t>"; "a <t> [MASK] </t> is a part of a mouse (…)"). A term counts when it weighs more in its slot than in the sense's own vector and in the other slot. Generic fillers (surface, system) are strong everywhere and cancel out. Hypernyms must also pass the substitution test.
- **Hyponyms and holonyms:** these are inverses. A hypernym found for *mouse* that is a ShiftNet sense gives that sense a hyponym *mouse*.
- **Target:** each target is matched to the sense, or taxonomy synset (e.g. `wn-animal-n`), whose definition fits best.

Open English WordNet (`wn`, lexicon `oewn:2024`, downloaded with `python -c "import wn; wn.download('oewn:2024')"`) is used only to lemmatise terms (rodents → rodent) and keep those of the right part of speech. Without it, raw vocabulary terms are used. Only whole words of the BERT vocabulary can come out: *rodent* is split into pieces, so it never appears.

On the 29 seed senses, quality is uneven. Concrete nouns do well (mouse, the animal: hypernyms *animal, pet*; meronyms *tail, head, leg, foot, body, fur*). Metaphorical senses and verbs are weak ("a timid person" still gets *animal*, at 0.56). Scores are therefore evidence for a person, not a decision.

Suggestions are stored in `relation_suggestions`. On the web app, **Contribute → Propose a relation** shows them next to the form, and the automatic checks of a proposed relation use them. A relation is published at once (validation `automatic`) only when both hold: the model scores it 0.6 or more, and the target word is in ShiftNet. Everything else goes to the review queue. A published hypernym or hyponym with a target sense or synset also adds the taxonomy edge, unless the parent is already an ancestor. Withdrawing the contribution removes both.

## MCP server

```sh
uv run shiftnet-mcp                                        # read-only tools, stdio
SHIFTNET_MCP_WRITE=1 uv run shiftnet-mcp                   # also save_senses, discover_senses, match/promote/reject
uv run shiftnet-mcp --transport streamable-http            # http://127.0.0.1:8000/mcp (stop `shiftnet serve` or move it with --port)
```

| Tool | Writes |
| --- | --- |
| `search_lexicon`, `get_word`, `get_sense` | no |
| `list_candidates`, `get_candidate`, `get_relation_suggestions` | no |
| `save_senses`, `add_attestation` | yes |
| `discover_senses` (slow: streams the corpus, runs the encoder) | yes |
| `match_candidate`, `promote_candidate`, `reject_candidate` | yes |
| `suggest_relations` (slow: runs the encoder over the senses) | yes |

Claude Code: `.mcp.json.example` at the repository root registers it. Copy it to `.mcp.json` (gitignored); it uses `SHIFTNET_DB`. A typical session: "run discovery for *stream*, then review the pending candidates". The assistant reads each cluster's usages, matches or rejects it, and drafts glosses for new senses.

## Tests

```sh
uv run pytest
```

Database tests run on a copy of a SQLite file seeded with `seed/seed.sql`; nothing else is needed. Discovery tests use a bag-of-words stand-in for the encoder.
