"""Sampling a lemma's usages from fineweb-edu.

fineweb-edu has one config per Common Crawl snapshot (CC-MAIN-2013-20 … CC-MAIN-2025-26), and each
document carries its crawl date. Sampling the same number of usages from several snapshots gives
every cluster a dated spread, so a sense that only appears in recent crawls stands out.
A crawl date is when the page was fetched: it bounds a usage from above, never from below.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from datetime import date

from ..models import CorpusUsage
from .text import forms_pattern, occurrences

CORPUS = "HuggingFaceFW/fineweb-edu"

# A spread of snapshots across the corpus, used when none are given.
DEFAULT_DUMPS = [
    "CC-MAIN-2013-20",
    "CC-MAIN-2015-14",
    "CC-MAIN-2017-04",
    "CC-MAIN-2019-04",
    "CC-MAIN-2021-04",
    "CC-MAIN-2023-06",
    "CC-MAIN-2024-10",
    "CC-MAIN-2025-05",
]

Doc = dict  # {"id", "text", "dump", "url", "date", ...}


def stream_dump(dump: str, data_files: str | list[str] | None = None) -> Iterator[Doc]:
    """Documents of one snapshot, streamed from the Hub (or from local parquet files)."""
    from datasets import load_dataset

    if data_files:
        ds = load_dataset("parquet", data_files=data_files, split="train", streaming=True)
    else:
        ds = load_dataset(CORPUS, name=dump, split="train", streaming=True)
    yield from ds


def parse_date(v: object) -> date | None:
    """fineweb dates look like 2013-05-18T07:24:47Z."""
    if isinstance(v, date):
        return v
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def sample_usages(
    docs: Iterable[Doc],
    forms: list[str],
    count_tokens: Callable[[str], int],
    max_tokens: int,
    limit: int,
    max_docs: int,
    max_per_doc: int = 2,
    dump: str | None = None,
) -> list[CorpusUsage]:
    """Up to `limit` usages from the first `max_docs` documents. Documents are prefiltered with a
    plain regex so only matching ones are sentence-split and tokenized."""
    pattern = forms_pattern(forms)
    out: list[CorpusUsage] = []
    for i, doc in enumerate(docs):
        if i >= max_docs or len(out) >= limit:
            break
        text = doc.get("text") or ""
        if not pattern.search(text):
            continue
        for occ in occurrences(text, pattern, count_tokens, max_tokens, max_per_doc=max_per_doc):
            out.append(
                CorpusUsage(
                    doc_id=str(doc.get("id")),
                    dump=doc.get("dump") or dump,
                    url=doc.get("url"),
                    crawled_on=parse_date(doc.get("date")),
                    context=occ.context,
                    target_start=occ.start,
                    target_end=occ.end,
                )
            )
            if len(out) >= limit:
                break
    return out
