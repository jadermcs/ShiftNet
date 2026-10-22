"""LexSPLADE: a sparse contextual word encoder. Each usage becomes a weighted bag of vocabulary
terms describing the marked word in its context (river bank → side, water, edge, shore)."""

from __future__ import annotations

import re

import numpy as np
from scipy import sparse

from ..models import CorpusUsage, Term

MODEL = "jadermcs/lexsplade-bert-large-silver"

_WORDLIKE = re.compile(r"^[a-z][a-z'\-]*$")


class Encoder:
    def __init__(self, model: str = MODEL, device: str | None = None, batch_size: int = 32):
        from sentence_transformers import SparseEncoder

        # trust_remote_code: the target-span pooling is a module shipped in the model repo.
        self.name = model
        self.model = SparseEncoder(model, trust_remote_code=True, device=device)
        self.tokenizer = self.model.tokenizer
        self.max_tokens = int(self.model.max_seq_length)
        self.batch_size = batch_size
        self.vocab = self.tokenizer.convert_ids_to_tokens(list(range(len(self.tokenizer))))

    def count_tokens(self, text: str) -> int:
        """Word pieces in the text, plus [CLS] and [SEP]."""
        return len(self.tokenizer.tokenize(text)) + 2

    def encode(self, usages: list[CorpusUsage], show_progress: bool = True) -> sparse.csr_matrix:
        """One L2-normalised row per usage."""
        if not usages:
            return sparse.csr_matrix((0, len(self.vocab)), dtype=np.float32)
        t = self.model.encode(
            [u.marked() for u in usages],
            batch_size=self.batch_size,
            convert_to_tensor=True,
            show_progress_bar=show_progress,
        )
        t = t.coalesce().cpu()
        idx = t.indices().numpy()
        m = sparse.csr_matrix(
            (t.values().float().numpy(), (idx[0], idx[1])), shape=tuple(t.shape), dtype=np.float32
        )
        return normalize_rows(m)

    def terms(self, row: np.ndarray | sparse.spmatrix, k: int = 12, exclude: set[str] = frozenset()) -> list[Term]:
        """The k strongest word-like dimensions of a vector, skipping word pieces, punctuation and
        the excluded terms (usually the target's own forms)."""
        v = np.asarray(row.todense() if sparse.issparse(row) else row).ravel()
        out: list[Term] = []
        for i in np.argsort(-v):
            if v[i] <= 0 or len(out) >= k:
                break
            tok = self.vocab[i]
            if _WORDLIKE.match(tok) and tok not in exclude:
                out.append(Term(term=tok, weight=round(float(v[i]), 4)))
        return out


def normalize_rows(m: sparse.csr_matrix) -> sparse.csr_matrix:
    norms = np.sqrt(np.asarray(m.multiply(m).sum(axis=1)).ravel())
    norms[norms == 0] = 1
    return sparse.diags(1 / norms) @ m
