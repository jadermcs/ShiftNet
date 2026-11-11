"""A bag-of-words stand-in for LexSPLADE, so pipeline tests run without the model."""

from __future__ import annotations

import re

import numpy as np
from scipy import sparse

from shiftnet_backend.discovery.encoder import Encoder, normalize_rows
from shiftnet_backend.models import CorpusUsage

VOCAB = [
    "[PAD]", ",", "##s", "cloud", "clouds",
    "sky", "rain", "storm", "dark", "grey", "white", "weather", "sun",
    "data", "server", "storage", "upload", "files", "computing", "online", "backup",
]


class _Tokenizer:
    def tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z]+|[^\sa-z]", text.lower())

    def __len__(self) -> int:
        return len(VOCAB)


class FakeEncoder(Encoder):
    def __init__(self, max_tokens: int = 64):
        self.name = "fake/bag-of-words"
        self.tokenizer = _Tokenizer()
        self.max_tokens = max_tokens
        self.batch_size = 8
        self.vocab = VOCAB
        self.words = VOCAB

    def encode(self, usages: list[CorpusUsage], show_progress: bool = True) -> sparse.csr_matrix:
        index = {t: i for i, t in enumerate(VOCAB)}
        m = np.zeros((len(usages), len(VOCAB)), dtype=np.float32)
        for r, u in enumerate(usages):
            m[r, index["cloud"]] = 1.0
            for w in self.tokenizer.tokenize(u.context):
                if w in index and w not in ("cloud", "clouds"):
                    m[r, index[w]] += 1.0
        return normalize_rows(sparse.csr_matrix(m))


class BagEncoder:
    """Bulk-stage stand-in: a marked context → counts of the vocabulary words around the target."""

    max_tokens = 64

    def __init__(self, words: list[str]):
        self.name = "fake/bag-of-words"
        self.vocab = ["[PAD]", *words]
        self._index = {w: i for i, w in enumerate(self.vocab)}

    def count_tokens(self, text: str) -> int:
        return len(text.split()) + 2

    def _bags(self, marked: list[str]) -> sparse.csr_matrix:
        m = np.zeros((len(marked), len(self.vocab)), dtype=np.float32)
        for r, text in enumerate(marked):
            for w in re.findall(r"[a-z]+", re.sub(r"<t>.*?</t>", " ", text).lower()):
                if w in self._index:
                    m[r, self._index[w]] += 1.0
        return sparse.csr_matrix(m)

    def encode_topk(self, marked: list[str], k: int = 128):
        from shiftnet_backend.discovery.encoder import to_topk

        return to_topk(self._bags(marked), k)

    def encode(self, usages: list[CorpusUsage], show_progress: bool = True) -> sparse.csr_matrix:
        return normalize_rows(self._bags([u.marked() for u in usages]))
