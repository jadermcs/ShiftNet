"""One discovery run: sample usages per snapshot, encode, cluster, describe each cluster and find
the closest sense already in the lexicon."""

from __future__ import annotations

import logging
import random
from collections import Counter
from collections.abc import Callable, Iterable

import numpy as np
from scipy import sparse

from ..models import Candidate, CorpusUsage, RunResult
from .cluster import cluster, nearest
from .corpus import CORPUS, DEFAULT_DUMPS, sample_usages, stream_dump
from .encoder import Encoder, normalize_rows
from .text import default_forms, forms_pattern, occurrences

log = logging.getLogger(__name__)


def discover(
    lemma: str,
    encoder: Encoder,
    forms: list[str] | None = None,
    dumps: list[str] | None = None,
    per_dump: int = 200,
    max_docs: int = 200_000,
    threshold: float = 0.35,
    min_size: int = 5,
    existing: dict[str, list[str]] | None = None,
    data_files: dict[str, str | list[str]] | None = None,
    stream: Callable[[str, str | list[str] | None], Iterable[dict]] = stream_dump,
    seed: int = 42,
) -> RunResult:
    """Discover candidate senses of `lemma`.

    per_dump usages are taken from each snapshot (scanning at most max_docs documents of it).
    existing maps sense ids to example sentences of senses already in the lexicon; each cluster
    records the closest of them. data_files maps a dump name to local parquet files to read instead
    of streaming it from the Hub.
    """
    forms = forms or default_forms(lemma)
    dumps = dumps or (list(data_files) if data_files else DEFAULT_DUMPS)
    usages: list[CorpusUsage] = []
    for dump in dumps:
        got = sample_usages(
            stream(dump, (data_files or {}).get(dump)),
            forms,
            encoder.count_tokens,
            encoder.max_tokens,
            limit=per_dump,
            max_docs=max_docs,
            dump=dump,
        )
        log.info("%s: %d usages", dump, len(got))
        usages.extend(got)

    random.Random(seed).shuffle(usages)  # clustering ties do not follow corpus order
    X = encoder.encode(usages)
    c = cluster(X, threshold=threshold, min_size=min_size)
    exclude = {t for f in forms for t in encoder.tokenizer.tokenize(f.lower())}

    sense_ids, prototypes = _prototypes(encoder, forms, existing or {})
    best, score = nearest(c.centroids, prototypes)

    candidates = []
    for k in range(c.centroids.shape[0]):
        members = [u for u, label in zip(usages, c.labels) if label == k]
        dates = sorted(u.crawled_on for u in members if u.crawled_on)
        candidates.append(
            Candidate(
                cluster=k,
                size=len(members),
                terms=encoder.terms(c.centroids[k], k=16, exclude=exclude),
                first_seen=dates[0] if dates else None,
                last_seen=dates[-1] if dates else None,
                year_counts=dict(sorted(Counter(str(d.year) for d in dates).items())),
                nearest_sense_id=sense_ids[best[k]] if best[k] >= 0 else None,
                nearest_score=round(float(score[k]), 4) if best[k] >= 0 else None,
            )
        )

    return RunResult(
        lemma=lemma,
        forms=forms,
        corpus="local parquet" if data_files else CORPUS,
        dumps=dumps,
        model=encoder.name,
        params={"per_dump": per_dump, "max_docs": max_docs, "threshold": threshold, "min_size": min_size, "seed": seed},
        candidates=candidates,
        usages=usages,
        assignments=[int(x) for x in c.labels],
        similarities=[None if np.isnan(s) else round(float(s), 4) for s in c.similarity],
        usage_terms=[encoder.terms(X[i], k=8, exclude=exclude) for i in range(X.shape[0])],
    )


def _prototypes(
    encoder: Encoder, forms: list[str], existing: dict[str, list[str]]
) -> tuple[list[str], sparse.csr_matrix]:
    """One vector per existing sense: the mean of its examples in which a form of the lemma occurs."""
    pattern = forms_pattern(forms)
    owners: list[str] = []
    probes: list[CorpusUsage] = []
    for sid, texts in existing.items():
        for text in texts:
            for occ in occurrences(text, pattern, encoder.count_tokens, encoder.max_tokens, max_per_doc=1, min_words=1):
                probes.append(CorpusUsage(doc_id=sid, context=occ.context, target_start=occ.start, target_end=occ.end))
                owners.append(sid)
    ids = list(dict.fromkeys(owners))
    if not probes:
        return ids, sparse.csr_matrix((0, len(encoder.vocab)), dtype=np.float32)
    V = encoder.encode(probes, show_progress=False)
    rows = [ids.index(o) for o in owners]
    member = sparse.csr_matrix((np.ones(len(rows)), (rows, range(len(rows)))), shape=(len(ids), len(rows)))
    return ids, normalize_rows(sparse.csr_matrix(member @ V))
