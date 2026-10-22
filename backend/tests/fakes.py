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

    def encode(self, usages: list[CorpusUsage], show_progress: bool = True) -> sparse.csr_matrix:
        index = {t: i for i, t in enumerate(VOCAB)}
        m = np.zeros((len(usages), len(VOCAB)), dtype=np.float32)
        for r, u in enumerate(usages):
            m[r, index["cloud"]] = 1.0
            for w in self.tokenizer.tokenize(u.context):
                if w in index and w not in ("cloud", "clouds"):
                    m[r, index[w]] += 1.0
        return normalize_rows(sparse.csr_matrix(m))
