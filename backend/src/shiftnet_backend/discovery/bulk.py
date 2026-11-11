"""Candidate senses for a whole vocabulary: the N most frequent content lemmas of fineweb-edu.

discover() handles one word. This runs the same method (LexSPLADE vectors, average-linkage
clusters) for every lemma at once, in stages that write to a work directory and can each be
re-run or resumed:

  download  the first shards of each snapshot, enough for --docs documents per snapshot
  count     pass 1 over those documents: occurrences of every word form, per snapshot
  vocab     lemmatise the forms (lemmatize.py) and keep the N most frequent content lemmas
  sample    pass 2: a uniform sample of each lemma's usages, the same quota per snapshot, each
            context cut to fit the encoder
  encode    LexSPLADE on every sampled usage, top-k dimensions kept; one process per GPU
  cluster   give each usage of an ambiguous form (leaves, saw) its lemma in context, then cluster
            each lemma's usages
  import    store the runs as discovery_runs / sense_candidates / corpus_usages, ready for review

Why it is fast:
- The passes read local parquet row groups in parallel, and a document is matched with one regex
  findall plus a set intersection. No per-word Python work happens for words that are not sampled.
- The counts give, for each lemma and snapshot, the probability that keeps its quota on average.
  So sampling is a single pass, and only kept occurrences are located, cut out and tokenised (in
  batches, with offsets).
- Vectors are fixed-width top-k arrays (512 bytes a usage), memory-mapped, so every later stage reads
  only the rows it needs. Usages are Arrow IPC files, also memory-mapped.
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import os
import re
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path

import numpy as np
from scipy import sparse

from ..models import Candidate, CorpusUsage, RunResult
from .cluster import MAX_USAGES, cluster, nearest
from .corpus import CORPUS, crawl_date
from .encoder import from_topk, normalize_rows, term_vocab, top_terms
from .lemmatize import learn, vocabulary, wordnet_morphy
from .text import context_at

log = logging.getLogger(__name__)

WORD = re.compile(r"(?<![\w-])[A-Za-z]+(?![\w-])")  # same boundaries as text.forms_pattern
LOWER_WORD = re.compile(r"(?<![\w-])[a-z]+(?![\w-])")
ROW_GROUPS_PER_TASK = 8  # fineweb-edu row groups hold ~1,000 documents
DOC_COLUMNS = ["text", "id", "url", "date", "file_path", "dump"]


# Work directory -------------------------------------------------------------------------------


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str))
    tmp.replace(path)


def _read_json(path: Path):
    return json.loads(path.read_text())


def _pool(workers: int, initializer=None, initargs=()):
    # spawn, not fork: the parent may hold torch / tokenizer threads.
    return get_context("spawn").Pool(workers, initializer=_init_worker, initargs=(initializer, initargs))


def _init_worker(initializer, initargs) -> None:
    from threadpoolctl import threadpool_limits

    threadpool_limits(1)  # one BLAS thread per process; the pool is the parallelism
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    if initializer:
        initializer(*initargs)


# download -------------------------------------------------------------------------------------


def download(workdir: Path, dumps: list[str], docs: int, local: Path | None = None, threads: int = 8) -> dict:
    """Pick the first shards of each snapshot that together hold at least `docs` documents, fetching
    them into the Hugging Face cache (or taking them from a local mirror: <local>/data/<dump>/*.parquet)."""
    import pyarrow.parquet as pq

    if local is None:
        from huggingface_hub import HfApi, hf_hub_download

        files = HfApi().list_repo_files(CORPUS, repo_type="dataset")

    def pick(dump: str) -> list[str]:
        if local is not None:
            names = sorted(str(p) for p in (local / "data" / dump).glob("*.parquet"))
        else:
            names = sorted(f for f in files if f.startswith(f"data/{dump}/") and f.endswith(".parquet"))
        out, n = [], 0
        for name in names:
            if n >= docs:
                break
            path = name if local is not None else hf_hub_download(CORPUS, name, repo_type="dataset")
            out.append(path)
            n += pq.ParquetFile(path).metadata.num_rows
        if n < docs:
            log.warning("%s: only %d documents", dump, n)
        log.info("%s: %d shards, %d documents", dump, len(out), n)
        return out

    with ThreadPoolExecutor(threads) as ex:
        picked = list(ex.map(pick, dumps))
    workdir.mkdir(parents=True, exist_ok=True)
    manifest = {"docs": docs, "dumps": dict(zip(dumps, picked))}
    _write_json(workdir / "manifest.json", manifest)
    return manifest


@dataclass(frozen=True)
class Task:
    index: int
    dump: str
    path: str
    row_groups: tuple[int, ...]


def tasks(manifest: dict) -> list[Task]:
    """The first manifest["docs"] documents of each snapshot, in batches of row groups. Both passes
    use this list, so the counts describe exactly the documents that are sampled."""
    import pyarrow.parquet as pq

    out: list[Task] = []
    for dump, paths in manifest["dumps"].items():
        left = manifest["docs"]
        for path in paths:
            md = pq.ParquetFile(path).metadata
            groups = []
            for g in range(md.num_row_groups):
                if left <= 0:
                    break
                groups.append(g)
                left -= md.row_group(g).num_rows
            for i in range(0, len(groups), ROW_GROUPS_PER_TASK):
                out.append(Task(len(out), dump, path, tuple(groups[i : i + ROW_GROUPS_PER_TASK])))
            if left <= 0:
                break
    return out


def _read(task: Task, columns: list[str]) -> dict[str, list]:
    import pyarrow.parquet as pq

    f = pq.ParquetFile(task.path)
    have = [c for c in columns if c in f.schema_arrow.names]
    t = f.read_row_groups(list(task.row_groups), columns=have)
    return {c: t.column(c).to_pylist() if c in have else [None] * t.num_rows for c in columns}


# count ----------------------------------------------------------------------------------------


def _count_task(task: Task) -> tuple[str, Counter, Counter]:
    raw: Counter[str] = Counter()
    for text in _read(task, ["text"])["text"]:
        if text:
            raw.update(WORD.findall(text))
    low: Counter[str] = Counter()
    caps: Counter[str] = Counter()
    for w, n in raw.items():
        lw = w.lower()
        low[lw] += n
        if w[0].isupper():
            caps[lw] += n
    return task.dump, low, caps


def count(workdir: Path, workers: int = os.cpu_count() or 1, min_total: int = 2) -> None:
    """Occurrences of every lowercase form per snapshot, and how many were capitalised. Forms seen
    fewer than min_total times in all are dropped (mostly typos and junk)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    manifest = _read_json(workdir / "manifest.json")
    ts = tasks(manifest)
    dumps = list(manifest["dumps"])
    per_dump = {d: Counter() for d in dumps}
    caps: Counter[str] = Counter()
    with _pool(workers) as pool:
        for i, (dump, low, cap) in enumerate(pool.imap_unordered(_count_task, ts), 1):
            per_dump[dump].update(low)
            caps.update(cap)
            if i % 50 == 0 or i == len(ts):
                log.info("count: %d/%d batches", i, len(ts))
    total: Counter[str] = Counter()
    for c in per_dump.values():
        total.update(c)
    forms = sorted(f for f, n in total.items() if n >= min_total)
    cols = {"form": forms, "total": [total[f] for f in forms], "capitalised": [caps[f] for f in forms]}
    for d in dumps:
        c = per_dump[d]
        cols[d] = [c.get(f, 0) for f in forms]
    pq.write_table(pa.table(cols), workdir / "counts.parquet")
    log.info("count: %d forms, %d tokens", len(forms), sum(total.values()))


# vocab ----------------------------------------------------------------------------------------


def build_vocab(
    workdir: Path,
    top: int = 20_000,
    min_count: int = 20,
    max_capitalised: float = 0.5,
    dictionary_only: bool = False,
    lexicon: str = "oewn:2024",
    morphy: Callable | None = None,
) -> dict:
    """Lemmatise the counted forms and keep the `top` most frequent content lemmas."""
    import pyarrow.parquet as pq

    manifest = _read_json(workdir / "manifest.json")
    dumps = list(manifest["dumps"])
    t = pq.read_table(workdir / "counts.parquet").to_pydict()
    counts = dict(zip(t["form"], t["total"]))
    capitalised = dict(zip(t["form"], t["capitalised"]))
    lemmas = learn(counts, morphy if morphy is not None else wordnet_morphy(lexicon), min_count=min_count,
                   capitalised=capitalised)
    ranked = vocabulary(lemmas, counts, capitalised, None, max_capitalised=max_capitalised, dictionary_only=dictionary_only)
    chosen = ranked[:top]
    # Competitors: other lemmas of the chosen lemmas' ambiguous forms (seed, for "seed" next to see).
    # They are sampled and clustered too, so that a usage can go to them when its context says so.
    top_set = {l for l, _ in chosen}
    rivals = {l for ls in lemmas.of.values() if len(ls) > 1 and top_set.intersection(ls) for l in ls} - top_set
    # Only a lemma with a form of its own (seeds) can win usages in context; said, made or times cannot.
    rivals &= {ls[0] for ls in lemmas.of.values() if len(ls) == 1}
    competitors = [(l, n) for l, n in ranked[top:] if l in rivals]
    chosen = chosen + competitors
    rank = {l: i for i, (l, _) in enumerate(chosen)}

    row = {f: i for i, f in enumerate(t["form"])}
    forms: dict[str, list[str]] = {}  # form → all its lemmas, for every form with at least one chosen
    by_lemma: dict[str, list[str]] = {l: [] for l in rank}
    for f, ls in lemmas.of.items():
        if any(l in rank for l in ls):
            forms[f] = list(ls)
            for l in ls:
                if l in rank:
                    by_lemma[l].append(f)
    entries = []
    for l, n in chosen:
        fs = sorted(by_lemma[l], key=lambda f: -counts[f])
        # Every occurrence of a form is offered to each of its lemmas, so a lemma's per-snapshot
        # count is the full count of its forms, ambiguous or not.
        entries.append({
            "lemma": l, "count": round(n), "forms": fs, "competitor": rank[l] >= top,
            "by_dump": [sum(t[d][row[f]] for f in fs) for d in dumps],
        })
    out = {
        "dumps": dumps,
        "params": {"top": top, "min_count": min_count, "max_capitalised": max_capitalised,
                   "dictionary_only": dictionary_only, "lexicon": lexicon},
        "rules": [list(r) for r in lemmas.rules[:200]],
        "lemmas": entries,
        "forms": forms,
    }
    _write_json(workdir / "vocab.json", out)
    ambiguous = sum(1 for ls in forms.values() if len(ls) > 1)
    log.info("vocab: %d lemmas (%d of them competitors), %d forms (%d ambiguous)", len(entries), len(competitors),
             len(forms), ambiguous)
    return out


# sample ---------------------------------------------------------------------------------------


class _S:  # per-worker sampling state, set by _init_sample
    table: dict[str, dict[str, tuple[float, tuple[tuple[int, float], ...]]]]
    offsets: Callable[[list[str]], list[list[tuple[int, int]]]]
    budget: int
    seed: int
    max_per_doc: int
    min_words: int
    patterns: dict[str, re.Pattern[str]] = {}


def regex_offsets(texts: list[str]) -> list[list[tuple[int, int]]]:
    """A stand-in tokeniser (words and punctuation), for tests and for models without offsets."""
    return [[m.span() for m in re.finditer(r"\w+|[^\w\s]", t)] for t in texts]


def _hf_offsets(model: str) -> Callable[[list[str]], list[list[tuple[int, int]]]]:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model)

    def offsets(texts: list[str]) -> list[list[tuple[int, int]]]:
        return tok(texts, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]

    return offsets


def _init_sample(table, tokenizer: str | None, budget: int, seed: int, max_per_doc: int, min_words: int) -> None:
    _S.table = table
    _S.offsets = _hf_offsets(tokenizer) if tokenizer else regex_offsets
    _S.budget, _S.seed, _S.max_per_doc, _S.min_words = budget, seed, max_per_doc, min_words
    _S.patterns = {}


def fit(context: str, start: int, end: int, offsets: list[tuple[int, int]], budget: int) -> tuple[str, int, int] | None:
    """Cut a context to `budget` tokens around its target, at word boundaries, keeping the target
    roughly centred. None when the target alone does not fit."""
    n = len(offsets)
    if n <= budget:
        return context, start, end
    t0 = next((i for i, (_, e) in enumerate(offsets) if e > start), n)
    t1 = next((i for i in range(n - 1, -1, -1) if offsets[i][0] < end), -1) + 1
    if t1 - t0 > budget or t0 >= t1:
        return None
    room = budget - (t1 - t0)
    right = min(n - t1, room // 2)
    left = min(t0, room - right)
    right = min(n - t1, room - left)
    a, b = t0 - left, t1 + right
    # Never cut inside a word: drop pieces glued to the cut (no space between them).
    while a < t0 and a > 0 and offsets[a][0] == offsets[a - 1][1]:
        a += 1
    while b > t1 and b < n and offsets[b][0] == offsets[b - 1][1]:
        b -= 1
    c0, c1 = offsets[a][0], offsets[b - 1][1]
    return context[c0:c1], start - c0, end - c0


def _sample_task(task: Task) -> dict[str, list]:
    table = _S.table[task.dump]
    keys = table.keys()
    rng = np.random.default_rng([_S.seed, task.index])
    docs = _read(task, DOC_COLUMNS)
    rows: dict[str, list] = {k: [] for k in ("doc_id", "dump", "url", "crawled_on", "context", "target_start",
                                             "target_end", "form", "pools", "key")}
    for i, text in enumerate(docs["text"]):
        if not text:
            continue
        low = text.lower()
        if len(low) != len(text):  # a few Unicode letters change length when lowercased
            continue
        words = LOWER_WORD.findall(low)
        present = keys & set(words)
        if not present:
            continue
        counts = Counter(words)
        fs = list(present)
        ns = np.fromiter((counts[f] for f in fs), np.int64, len(fs))
        qs = np.fromiter((table[f][0] for f in fs), np.float64, len(fs))
        ks = rng.binomial(ns, qs)
        doc = None
        for j in np.flatnonzero(ks):
            f, n = fs[j], int(ns[j])
            q, pools = table[f]
            pattern = _S.patterns.get(f)
            if pattern is None:
                pattern = _S.patterns[f] = re.compile(rf"(?<![\w-]){f}(?![\w-])")
            spans = [m.span() for m in pattern.finditer(low)]
            for p in sorted(rng.choice(n, min(int(ks[j]), _S.max_per_doc), replace=False)):
                s, e = spans[p]
                occ = context_at(text, s, e, min_words=_S.min_words)
                if occ is None:
                    continue
                # One uniform key per occurrence, below q; the occurrence joins each pool whose own
                # probability exceeds it, so each pool is a uniform sample at its own rate.
                u = rng.random() * q
                kept = [l for l, pl in pools if u < pl]
                if not kept:
                    continue
                if doc is None:
                    doc = {c: docs[c][i] for c in DOC_COLUMNS if c != "text"}
                    doc["crawled_on"] = crawl_date(doc, task.dump)
                rows["doc_id"].append(str(doc["id"]))
                rows["dump"].append(doc["dump"] or task.dump)
                rows["url"].append(doc["url"])
                rows["crawled_on"].append(doc["crawled_on"])
                rows["context"].append(occ.context)
                rows["target_start"].append(occ.start)
                rows["target_end"].append(occ.end)
                rows["form"].append(f)
                rows["pools"].append(kept)
                rows["key"].append(u)
    # Cut every context to the encoder, in batched tokeniser calls. Not one call for the whole task:
    # ~120k contexts' offsets as Python tuples take about 1 GB per worker.
    keep, ctxs = [], rows["context"]
    for a in range(0, len(ctxs), 4096):
        for r, offs in enumerate(_S.offsets(ctxs[a : a + 4096]), a):
            got = fit(ctxs[r], rows["target_start"][r], rows["target_end"][r], offs, _S.budget)
            if got:
                ctxs[r], rows["target_start"][r], rows["target_end"][r] = got
                keep.append(r)
    return {k: [v[r] for r in keep] for k, v in rows.items()}


def sample(
    workdir: Path,
    per_lemma: int = 2000,
    tokenizer: str | None = None,
    max_tokens: int = 64,
    oversample: float = 1.5,
    max_per_doc: int = 2,
    min_words: int = 6,
    seed: int = 42,
    workers: int = os.cpu_count() or 1,
) -> None:
    """Up to per_lemma usages of every vocabulary lemma, the same quota from each snapshot."""
    import pyarrow as pa
    import pyarrow.feather as feather

    manifest = _read_json(workdir / "manifest.json")
    vocab = _read_json(workdir / "vocab.json")
    dumps = vocab["dumps"]
    quota = math.ceil(per_lemma / len(dumps))
    lemma_ids = {e["lemma"]: i for i, e in enumerate(vocab["lemmas"])}
    names = [e["lemma"] for e in vocab["lemmas"]]

    # form → (max probability, ((lemma, probability), ...)) per snapshot
    table: dict[str, dict] = {}
    for d, dump in enumerate(dumps):
        p = {i: min(1.0, oversample * quota / e["by_dump"][d]) if e["by_dump"][d] else 0.0
             for i, e in enumerate(vocab["lemmas"])}
        t = {}
        for f, ls in vocab["forms"].items():
            pools = tuple((lemma_ids[l], p[lemma_ids[l]]) for l in ls if l in lemma_ids and p[lemma_ids[l]] > 0)
            if pools:
                t[f] = (max(pl for _, pl in pools), pools)
        table[dump] = t

    out = workdir / "usages"
    out.mkdir(exist_ok=True)
    # [CLS] … [SEP] and the two markers, which are single tokens of the LexSPLADE vocabulary, plus
    # slack for byte-level BPE (RoBERTa): a stray space token before <t>, and a target that loses its
    # leading space can split into more pieces (Ġdoomscrolling → d·oom·sc·rolling).
    budget = max_tokens - 8
    by_dump: dict[str, list[Task]] = {}
    for t in tasks(manifest):
        by_dump.setdefault(t.dump, []).append(t)
    with _pool(workers, _init_sample, (table, tokenizer, budget, seed, max_per_doc, min_words)) as pool:
        for dump in dumps:
            path = out / f"{dump}.arrow"
            if path.exists():
                log.info("sample: %s done already", dump)
                continue
            # An oversampled snapshot is ~7M rows: each batch goes to disk as it arrives (with hashes of
            # its document and lower-cased context), and only the kept rows are read back. Holding
            # them in memory once ran a 30 GB machine out of memory. A crash resumes from the parts.
            spool = out / f"{dump}.parts"
            spool.mkdir(exist_ok=True)
            todo = [t for t in by_dump.get(dump, []) if not (spool / f"{t.index:06d}.arrow").exists()]
            for i, (index, rows) in enumerate(pool.imap_unordered(_sample_part, todo), 1):
                if not rows["form"]:
                    continue
                part = pa.Table.from_pydict(rows)
                del rows
                part = part.append_column("doc_h", pa.array(_hash_strings(part.column("doc_id"))))
                part = part.append_column("ctx_h", pa.array(_hash_strings(part.column("context"), lower=True)))
                tmp = spool / f"{index:06d}.tmp"
                feather.write_feather(part, tmp, compression="uncompressed")
                tmp.replace(spool / f"{index:06d}.arrow")
                del part
                if i % 10 == 0:
                    log.info("sample %s: %d/%d batches", dump, i, len(todo))
            files = sorted(spool.glob("*.arrow"))
            mapped = pa.concat_tables([pa.ipc.open_file(pa.memory_map(str(p))).read_all() for p in files]) if files else None
            if mapped is None or not mapped.num_rows:
                log.warning("sample: nothing in %s", dump)
                continue
            rows_kept, pools = _take_quota(mapped.select(["pools", "key", "doc_h", "ctx_h"]), quota, max_per_doc)
            t = mapped.drop(["key", "pools", "doc_h", "ctx_h"]).take(pa.array(rows_kept))
            del mapped
            t = t.append_column("pools", pa.array([[names[i] for i in ids] for ids in pools], pa.list_(pa.string())))
            tmp = path.with_suffix(".tmp")
            feather.write_feather(t, tmp, compression="uncompressed")  # memory-mappable
            tmp.replace(path)
            log.info("sample %s: %d usages for %d lemmas", dump, t.num_rows, len({l for ls in pools for l in ls}))
            del t
            for p in files:
                p.unlink()
            spool.rmdir()


def _hash_strings(col, lower: bool = False, chunk: int = 1 << 20) -> np.ndarray:
    """64-bit hashes of an Arrow string column, a chunk at a time (the strings are never all Python objects)."""
    import pandas as pd
    import pyarrow.compute as pc

    out = np.empty(len(col), dtype=np.uint64)
    for a in range(0, len(col), chunk):
        c = col.slice(a, chunk)
        if lower:
            c = pc.utf8_lower(c)
        out[a : a + len(c)] = pd.util.hash_array(np.asarray(c.to_numpy(zero_copy_only=False), dtype=object))
    return out


def _sample_part(task: Task) -> tuple[int, dict[str, list]]:
    return task.index, _sample_task(task)


def _take_quota(t, quota: int, max_per_doc: int) -> tuple[np.ndarray, list[list[int]]]:
    """Per lemma: the `quota` lowest keys, at most max_per_doc per document, no repeated context.
    `t` holds pools (lemma ids), key, doc_h and ctx_h (hashes of the document id and the lower-cased
    context); returns the kept rows of `t` and each one's lemma ids."""
    import pandas as pd

    pools = t.column("pools").combine_chunks()
    lens = np.asarray(pools.value_lengths())
    pairs = pd.DataFrame({
        "row": np.repeat(np.arange(t.num_rows), lens),
        "pools": np.asarray(pools.flatten()),
        "key": np.repeat(t.column("key").to_numpy(), lens),
        "doc": np.repeat(t.column("doc_h").to_numpy(), lens),
        "ctx": np.repeat(t.column("ctx_h").to_numpy(), lens),
    })
    pairs = pairs.sort_values(["pools", "key"], kind="stable")
    pairs = pairs[~pairs.duplicated(["pools", "ctx"])]
    pairs = pairs[pairs.groupby(["pools", "doc"]).cumcount() < max_per_doc]
    pairs = pairs[pairs.groupby("pools").cumcount() < quota]
    kept = pairs.groupby("row")["pools"].agg(list)
    return kept.index.to_numpy(), kept.tolist()


def load_usages(workdir: Path):
    """All sampled usages as one memory-mapped Arrow table, snapshots in vocabulary order."""
    import pyarrow as pa

    vocab = _read_json(workdir / "vocab.json")
    tables = []
    for dump in vocab["dumps"]:
        path = workdir / "usages" / f"{dump}.arrow"
        if path.exists():
            tables.append(pa.ipc.open_file(pa.memory_map(str(path))).read_all())
    return pa.concat_tables(tables)


def take_rows(table, ids) -> "pa.Table":
    """table.take(ids) for a table of memory-mapped batches, in the order of ids. Arrow's own take
    first concatenates every chunk of a string column, which overflows its 32-bit offsets past 2 GB
    of text (8 snapshots are ~12 GB) and would copy it all into memory anyway."""
    import pyarrow as pa

    ids = np.asarray(ids, dtype=np.int64)
    batches = table.to_batches()
    starts = np.cumsum([0] + [b.num_rows for b in batches])
    which = np.searchsorted(starts, ids, side="right") - 1
    order = np.argsort(which, kind="stable")
    parts = []
    for b in np.unique(which):
        sel = order[which[order] == b]
        parts.append((sel, batches[b].take(pa.array(ids[sel] - starts[b]))))
    if not parts:
        return table.schema.empty_table()
    out = pa.Table.from_batches([p for _, p in parts], schema=table.schema)
    back = np.empty(len(ids), dtype=np.int64)
    back[np.concatenate([sel for sel, _ in parts])] = np.arange(len(ids))
    return out.take(pa.array(back))  # back to the order of ids; out is small


# encode ---------------------------------------------------------------------------------------


def _marked(t) -> list[str]:
    ctx = t.column("context").to_pylist()
    s = t.column("target_start").to_pylist()
    e = t.column("target_end").to_pylist()
    return [f"{c[:a]}<t>{c[a:b]}</t>{c[b:]}" for c, a, b in zip(ctx, s, e)]  # as CorpusUsage.marked


def encode(workdir: Path, encoder, shard: int = 0, shards: int = 1, k: int = 128, chunk: int = 4096) -> None:
    """Encode this shard's slice of the usages (contiguous rows), resuming where it stopped.
    Run one process per GPU: CUDA_VISIBLE_DEVICES=i shiftnet bulk encode --shard i --shards n."""
    from numpy.lib.format import open_memmap

    usages = load_usages(workdir)
    n = usages.num_rows
    lo, hi = shard * n // shards, (shard + 1) * n // shards
    out = workdir / "vectors"
    out.mkdir(exist_ok=True)
    meta = {"model": encoder.name, "k": k, "dim": len(encoder.vocab), "rows": n, "shards": shards}
    if shard == 0 or not (out / "meta.json").exists():
        _write_json(out / "meta.json", {**meta, "vocab": list(encoder.vocab)})
    stem = out / f"{shard:03d}-of-{shards:03d}"
    progress = stem.with_suffix(".json")
    done = 0
    if progress.exists():
        p = _read_json(progress)
        if (p["lo"], p["hi"], p["model"], p["k"]) != (lo, hi, encoder.name, k):
            raise ValueError(f"{progress} was written for other rows or another model: delete the vectors to start over")
        done = p["done"]
    mode = "r+" if done else "w+"
    dtype = np.uint16 if len(encoder.vocab) <= 65536 else np.int32
    idx = open_memmap(f"{stem}.idx.npy", mode=mode, dtype=dtype, shape=(hi - lo, k))
    val = open_memmap(f"{stem}.val.npy", mode=mode, dtype=np.float16, shape=(hi - lo, k))
    for a in range(lo + done, hi, chunk):
        b = min(hi, a + chunk)
        i, v = encoder.encode_topk(_marked(usages.slice(a, b - a)), k)
        idx[a - lo : b - lo], val[a - lo : b - lo] = i.astype(dtype), v
        idx.flush()
        val.flush()
        _write_json(progress, {"lo": lo, "hi": hi, "done": b - lo, "model": encoder.name, "k": k})
        log.info("encode shard %d: %d/%d", shard, b - lo, hi - lo)
    if hi == lo:
        _write_json(progress, {"lo": lo, "hi": hi, "done": 0, "model": encoder.name, "k": k})


class Vectors:
    """The encoded usages, memory-mapped; rows(ids) gives L2-normalised sparse rows."""

    def __init__(self, workdir: Path):
        out = workdir / "vectors"
        self.meta = _read_json(out / "meta.json")
        parts = []
        for p in sorted(out.glob(f"*-of-{self.meta['shards']:03d}.json")):
            m = _read_json(p)
            if m["done"] != m["hi"] - m["lo"]:
                raise ValueError(f"{p.name}: shard not finished ({m['done']}/{m['hi'] - m['lo']})")
            stem = str(p)[: -len(".json")]
            parts.append((m["lo"], np.load(f"{stem}.idx.npy", mmap_mode="r"), np.load(f"{stem}.val.npy", mmap_mode="r")))
        parts.sort(key=lambda t: t[0])
        covered = sum(len(i) for _, i, _ in parts)
        if covered != self.meta["rows"]:
            raise ValueError(f"vectors cover {covered} of {self.meta['rows']} usages: some shards are missing")
        self.starts = np.array([lo for lo, _, _ in parts])
        self.parts = parts
        self.dim = self.meta["dim"]
        self.vocab = self.meta["vocab"]
        self.words = term_vocab(self.vocab)

    def arrays(self, ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Top-k indices and L2-normalised float32 weights of the given rows, in their order."""
        ids = np.asarray(ids, dtype=np.int64)
        k = self.meta["k"]
        I = np.zeros((len(ids), k), dtype=np.int32)
        V = np.zeros((len(ids), k), dtype=np.float32)
        which = np.searchsorted(self.starts, ids, side="right") - 1
        for p in np.unique(which):
            lo, idx, val = self.parts[p]
            m = np.flatnonzero(which == p)
            local = ids[m] - lo
            order = np.argsort(local, kind="stable")  # sorted reads from the memory map
            I[m[order]] = idx[local[order]]
            V[m[order]] = val[local[order]]
        norms = np.sqrt((V * V).sum(axis=1, keepdims=True))
        return I, V / np.where(norms == 0, 1, norms)

    def rows(self, ids: np.ndarray) -> sparse.csr_matrix:
        """L2-normalised sparse rows, in the given order."""
        I, V = self.arrays(ids)
        return from_topk(I, V, self.dim)


# cluster --------------------------------------------------------------------------------------


def resolve(
    forms: np.ndarray,
    form_lemmas: list[tuple[int, ...]],
    vectors: Vectors,
    n_lemmas: int,
    min_support: int = 20,
    chunk: int = 500_000,
) -> np.ndarray:
    """The lemma of every usage. forms: per usage, an index into form_lemmas, which lists each
    form's lemmas (vocabulary indices, most frequent first; -1 for a lemma outside the vocabulary).

    A usage of an unambiguous form takes its lemma. A usage of an ambiguous one goes to the lemma
    whose centroid of unambiguous usages it is closest to (cosine): "leaves" next to branches goes to leaf,
    next to the office to leave. Lemmas with fewer than min_support unambiguous usages cannot win;
    if no candidate can, the most frequent one in the vocabulary is taken.
    """
    n = len(forms)
    single = np.array([ls[0] if len(ls) == 1 else -1 for ls in form_lemmas], dtype=np.int64)
    label = single[forms]
    ambiguous_forms = [f for f, ls in enumerate(form_lemmas) if len(ls) > 1]
    if not ambiguous_forms:
        return label
    contested = sorted({l for f in ambiguous_forms for l in form_lemmas[f] if l >= 0})
    slot = np.full(n_lemmas, -1)
    slot[contested] = np.arange(len(contested))

    # Centroids of the contested lemmas, from their unambiguous usages: dense, contested × vocabulary.
    support = np.zeros(len(contested), dtype=np.int64)
    C = np.zeros((len(contested), vectors.dim), dtype=np.float32)
    for a in range(0, n, chunk):
        ids = np.arange(a, min(n, a + chunk))
        ids = ids[(label[ids] >= 0) & (slot[np.maximum(label[ids], 0)] >= 0)]
        if not len(ids):
            continue
        s = slot[label[ids]]
        member = sparse.csr_matrix((np.ones(len(ids), np.float32), (s, np.arange(len(ids)))),
                                   shape=(len(contested), len(ids)))
        m = (member @ vectors.rows(ids)).tocoo()
        C[m.row, m.col] += m.data  # a matrix product has no duplicate entries
        support += np.bincount(s, minlength=len(contested))
    norms = np.linalg.norm(C, axis=1, keepdims=True)
    C /= np.where(norms == 0, 1, norms)
    eligible = support >= min_support

    is_amb = np.zeros(len(form_lemmas), bool)
    is_amb[ambiguous_forms] = True
    rows = np.flatnonzero(is_amb[forms])
    step = max(1, chunk // 5)
    for a in range(0, len(rows), step):
        ids = rows[a : a + step]
        I, V = vectors.arrays(ids)
        rr, cc, fallback = [], [], np.full(len(ids), -1)
        for r, f in enumerate(forms[ids]):
            ls = [l for l in form_lemmas[f] if l >= 0]
            fallback[r] = ls[0] if ls else -1
            for l in ls:
                if eligible[slot[l]]:
                    rr.append(r)
                    cc.append(l)
        rr, cc = np.array(rr, dtype=np.int64), np.array(cc, dtype=np.int64)
        best = fallback.copy()
        if len(rr):
            # cosine of each usage with each candidate centroid, reading only the usage's k dimensions
            score = (C[slot[cc][:, None], I[rr]] * V[rr]).sum(axis=1)
            order = np.lexsort((-score, rr))  # by row, best score first
            first = order[np.r_[True, rr[order][1:] != rr[order][:-1]]]
            best[rr[first]] = cc[first]
        label[ids] = best
    return label


class _C:  # per-worker clustering state
    usages = None
    vectors: Vectors
    names: list[str]
    forms: dict[str, list[str]]
    opts: dict


def _init_cluster(workdir: str, names: list[str], forms: dict[str, list[str]], opts: dict) -> None:
    _C.usages = load_usages(Path(workdir))
    _C.vectors = Vectors(Path(workdir))
    _C.names, _C.forms, _C.opts = names, forms, opts


def cluster_lemma(lemma: str, forms: list[str], ids: np.ndarray, usages, vectors: Vectors, dumps: list[str],
                  threshold: float, min_size: int, typical: int, borderline: int, seed: int) -> dict:
    """One lemma's usages → a stored run (RunResult JSON) plus its centroids (top 256 dimensions)."""
    ids = np.random.default_rng(seed).permutation(ids)  # clustering ties do not follow corpus order
    X = vectors.rows(ids)
    c = cluster(X, threshold=threshold, min_size=min_size)
    exclude = {lemma, *forms}
    t = take_rows(usages, ids).select(["doc_id", "dump", "url", "crawled_on", "context", "target_start", "target_end"]).to_pydict()

    candidates, keep = [], []
    for k in range(c.centroids.shape[0]):
        members = np.flatnonzero(c.labels == k)
        dates = sorted(d for d in (t["crawled_on"][i] for i in members) if d)
        candidates.append(Candidate(
            cluster=k, size=len(members), terms=top_terms(vectors.words, c.centroids[k], 16, exclude),
            first_seen=dates[0] if dates else None, last_seen=dates[-1] if dates else None,
            year_counts=dict(sorted(Counter(str(d.year) for d in dates).items())),
        ))
        by_sim = members[np.argsort(-c.similarity[members], kind="stable")]
        keep.extend(by_sim[:typical])
        keep.extend(by_sim[typical:][-borderline:] if borderline else [])
    keep = sorted(set(int(i) for i in keep))

    run = RunResult(
        lemma=lemma, forms=forms, corpus=CORPUS, dumps=dumps, model=vectors.meta["model"],
        params={"threshold": threshold, "min_size": min_size, "seed": seed},
        candidates=candidates,
        usages=[CorpusUsage(
            doc_id=t["doc_id"][i], dump=t["dump"][i], url=t["url"][i], crawled_on=t["crawled_on"][i],
            context=t["context"][i], target_start=t["target_start"][i], target_end=t["target_end"][i],
        ) for i in keep],
        assignments=[int(c.labels[i]) for i in keep],
        similarities=[round(float(c.similarity[i]), 4) for i in keep],
        usage_terms=[top_terms(vectors.words, X[i], 8, exclude) for i in keep],
        usage_count=len(ids),
        noise_count=int((c.labels == -1).sum()),
    )
    cents = []
    for k in range(c.centroids.shape[0]):
        row = c.centroids[k]
        top = np.argsort(-row.data)[:256]
        cents.append({"idx": row.indices[top].tolist(), "val": np.round(row.data[top], 4).tolist()})
    return {"run": run.model_dump(mode="json"), "centroids": cents}


def _cluster_batch(job: tuple[str, list[tuple[int, np.ndarray]]]) -> str:
    path, items = job
    o = _C.opts
    lines = []
    for li, ids in items:
        lemma = _C.names[li]
        res = cluster_lemma(lemma, _C.forms.get(lemma, []), ids, _C.usages, _C.vectors, o["dumps"],
                            o["threshold"], o["min_size"], o["typical"], o["borderline"], o["seed"] + li)
        lines.append(json.dumps(res, ensure_ascii=False))
    tmp = Path(path + ".tmp")
    with gzip.open(tmp, "wt") as f:
        f.write("\n".join(lines) + "\n")
    tmp.replace(path)
    return path


def cluster_all(
    workdir: Path,
    threshold: float = 0.35,
    min_size: int = 10,
    min_usages: int = 50,
    max_usages: int = 2500,
    typical: int = 15,
    borderline: int = 5,
    min_support: int = 20,
    seed: int = 42,
    batch: int = 50,
    workers: int = os.cpu_count() or 1,
) -> None:
    """Resolve ambiguous forms, then cluster each lemma with at least min_usages usages (at most
    max_usages, a random subset). Each candidate keeps its `typical` usages closest to the centroid
    and `borderline` farthest ones for review; the others are counted, not stored."""
    import pyarrow.compute as pc

    vocab = _read_json(workdir / "vocab.json")
    names = [e["lemma"] for e in vocab["lemmas"]]
    index = {l: i for i, l in enumerate(names)}
    forms_of = {e["lemma"]: e["forms"] for e in vocab["lemmas"]}
    usages = load_usages(workdir)
    vectors = Vectors(workdir)

    enc = pc.dictionary_encode(usages.column("form").combine_chunks())  # one dictionary for all snapshots
    form_names = enc.dictionary.to_pylist()
    forms = enc.indices.to_numpy(zero_copy_only=False).astype(np.int64)
    form_lemmas = [tuple(index.get(l, -1) for l in vocab["forms"].get(f, [])) for f in form_names]
    label = resolve(forms, form_lemmas, vectors, len(names), min_support=min_support)

    order = np.argsort(label, kind="stable")
    bounds = np.flatnonzero(np.diff(label[order])) + 1
    groups = []
    rng = np.random.default_rng(seed)
    for ids in np.split(order, bounds):
        li = int(label[ids[0]]) if len(ids) else -1
        if li < 0 or len(ids) < min_usages:
            continue
        cap = min(max_usages, MAX_USAGES)
        groups.append((li, np.sort(rng.choice(ids, cap, replace=False)) if len(ids) > cap else ids))
    groups.sort(key=lambda g: g[0])  # vocabulary order: frequent lemmas first
    log.info("cluster: %d lemmas with %d+ usages (of %d)", len(groups), min_usages, len(names))

    out = workdir / "runs"
    out.mkdir(exist_ok=True)
    jobs = []
    for b in range(0, len(groups), batch):
        path = out / f"{b // batch:05d}.jsonl.gz"
        if not path.exists():
            jobs.append((str(path), groups[b : b + batch]))
    opts = {"dumps": vocab["dumps"], "threshold": threshold, "min_size": min_size, "typical": typical,
            "borderline": borderline, "seed": seed}
    with _pool(workers, _init_cluster, (str(workdir), names, forms_of, opts)) as pool:
        for i, _ in enumerate(pool.imap_unordered(_cluster_batch, jobs), 1):
            log.info("cluster: %d/%d batches", i, len(jobs))


def runs(workdir: Path) -> Iterator[dict]:
    for path in sorted((workdir / "runs").glob("*.jsonl.gz")):
        with gzip.open(path, "rt") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


# import ---------------------------------------------------------------------------------------


def import_runs(conn_factory, workdir: Path, tag: str, encoder_factory: Callable[[], object], per_tx: int = 100) -> int:
    """Store every clustered lemma not yet imported under `tag` (params.bulk). For a lemma already in
    the lexicon, each candidate records the nearest existing sense, as in discover(). The encoder is
    only loaded if some lemma needs it. Returns the number of runs stored."""
    from .. import lexicon
    from .pipeline import _prototypes
    from .store import save_run

    with conn_factory(False) as conn:
        done = {r["lemma"] for r in conn.execute(
            "select lemma from discovery_runs where bulk_tag = ?", (tag,))}
        known = {r["l"] for r in conn.execute("select distinct lemma_key as l from senses")}
    encoder = None
    stored = 0
    pending: list[RunResult] = []

    def flush():
        nonlocal stored
        if pending:
            with conn_factory(True) as conn:
                for r in pending:
                    save_run(conn, r)
            stored += len(pending)
            log.info("import: %d runs", stored)
            pending.clear()

    with conn_factory(False) as read:
        for item in runs(workdir):
            r = RunResult.model_validate(item["run"])
            if r.lemma in done:
                continue
            r.params = {**r.params, "bulk": tag}
            existing = lexicon.sense_texts(read, r.lemma) if r.lemma in known and r.candidates else {}
            if existing:
                encoder = encoder or encoder_factory()
                sense_ids, prototypes = _prototypes(encoder, r.forms, existing)
                cents = item["centroids"]
                C = normalize_rows(sparse.csr_matrix(
                    (np.concatenate([c["val"] for c in cents]).astype(np.float32),
                     np.concatenate([c["idx"] for c in cents]).astype(np.int32),
                     np.cumsum([0] + [len(c["idx"]) for c in cents])),
                    shape=(len(cents), prototypes.shape[1]),
                ))
                best, score = nearest(C, prototypes)
                for c in r.candidates:
                    if best[c.cluster] >= 0:
                        c.nearest_sense_id = sense_ids[best[c.cluster]]
                        c.nearest_score = round(float(score[c.cluster]), 4)
            pending.append(r)
            if len(pending) >= per_tx:
                flush()
    flush()
    return stored


def describe(workdir: Path) -> dict:
    """What each stage has produced so far."""
    out: dict = {}
    if (p := workdir / "manifest.json").exists():
        m = _read_json(p)
        out["download"] = {"docs_per_dump": m["docs"], "shards": {d: len(v) for d, v in m["dumps"].items()}}
    if (workdir / "counts.parquet").exists():
        import pyarrow.parquet as pq

        out["count"] = {"forms": pq.ParquetFile(workdir / "counts.parquet").metadata.num_rows}
    if (p := workdir / "vocab.json").exists():
        v = _read_json(p)
        out["vocab"] = {"lemmas": len(v["lemmas"]), "forms": len(v["forms"]),
                        "ambiguous_forms": sum(1 for ls in v["forms"].values() if len(ls) > 1),
                        "first": [e["lemma"] for e in v["lemmas"][:10]]}
    if (workdir / "usages").exists():
        out["sample"] = {p.stem: _arrow_rows(p) for p in sorted((workdir / "usages").glob("*.arrow"))}
    if (workdir / "vectors").exists():
        out["encode"] = {}
        for p in sorted((workdir / "vectors").glob("*-of-*.json")):
            m = _read_json(p)
            out["encode"][p.stem] = f"{m['done']}/{m['hi'] - m['lo']}"
    if (workdir / "runs").exists():
        out["cluster"] = {"batches": len(list((workdir / "runs").glob("*.jsonl.gz")))}
    return out


def _arrow_rows(path: Path) -> int:
    import pyarrow as pa

    return pa.ipc.open_file(pa.memory_map(str(path))).read_all().num_rows

