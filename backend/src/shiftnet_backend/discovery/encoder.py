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
    def __init__(self, model: str = MODEL, device: str | None = None, batch_size: int = 32, dtype: str | None = None):
        from sentence_transformers import SparseEncoder

        # trust_remote_code: the target-span pooling is a module shipped in the model repo.
        self.name = model
        self.model = SparseEncoder(model, trust_remote_code=True, device=device)
        if dtype:  # bfloat16 / float16 on a GPU: about twice the throughput
            import torch

            self.model.to(getattr(torch, dtype))
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
        return normalize_rows(sparse_tensor_to_csr(t))

    def encode_topk(self, marked: list[str], k: int = 128, show_progress: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """Already marked texts → the k strongest dimensions of each vector: indices (uint16 when the
        vocabulary fits) and float16 weights, zero-padded, not normalised. LexSPLADE uses about 225
        dimensions per usage; the top 128 move cosine similarities by 0.03 at most."""
        t = self.model.encode(
            marked, batch_size=self.batch_size, convert_to_tensor=True, max_active_dims=k,
            show_progress_bar=show_progress,
        )
        return to_topk(sparse_tensor_to_csr(t), k)

    def terms(self, row: np.ndarray | sparse.spmatrix, k: int = 12, exclude: set[str] = frozenset()) -> list[Term]:
        """The k strongest word-like dimensions of a vector, skipping word pieces, punctuation and
        the excluded terms (usually the target's own forms)."""
        return top_terms(self.vocab, row, k, exclude)


def top_terms(vocab: list[str], row: np.ndarray | sparse.spmatrix, k: int = 12, exclude: set[str] = frozenset()) -> list[Term]:
    if sparse.issparse(row):
        row = sparse.csr_matrix(row)
        ids, v = row.indices, row.data
    else:
        v = np.asarray(row).ravel()
        ids = np.arange(len(v))
    out: list[Term] = []
    for j in np.argsort(-v, kind="stable"):
        if v[j] <= 0 or len(out) >= k:
            break
        tok = vocab[ids[j]]
        if _WORDLIKE.match(tok) and tok not in exclude:
            out.append(Term(term=tok, weight=round(float(v[j]), 4)))
    return out


def sparse_tensor_to_csr(t) -> sparse.csr_matrix:
    t = t.coalesce().cpu()
    idx = t.indices().numpy()
    return sparse.csr_matrix((t.values().float().numpy(), (idx[0], idx[1])), shape=tuple(t.shape), dtype=np.float32)


def to_topk(m: sparse.csr_matrix, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Fixed-width top-k arrays of a sparse matrix, rows padded with (0, 0.0)."""
    m = sparse.csr_matrix(m)
    m.sum_duplicates()
    n = m.shape[0]
    idx = np.zeros((n, k), dtype=np.uint16 if m.shape[1] <= 65536 else np.int32)
    val = np.zeros((n, k), dtype=np.float16)
    for r in range(n):
        a, b = m.indptr[r], m.indptr[r + 1]
        d, i = m.data[a:b], m.indices[a:b]
        if b - a > k:
            keep = np.argpartition(-d, k - 1)[:k]
            d, i = d[keep], i[keep]
        idx[r, : len(i)] = i
        val[r, : len(d)] = d
    return idx, val


def from_topk(idx: np.ndarray, val: np.ndarray, dim: int) -> sparse.csr_matrix:
    """The inverse of to_topk, rows L2-normalised."""
    n, k = idx.shape
    m = sparse.csr_matrix(
        (val.astype(np.float32).ravel(), idx.astype(np.int32).ravel(), np.arange(0, n * k + 1, k)), shape=(n, dim)
    )
    m.eliminate_zeros()
    m.sum_duplicates()
    return normalize_rows(m)


def normalize_rows(m: sparse.csr_matrix) -> sparse.csr_matrix:
    norms = np.sqrt(np.asarray(m.multiply(m).sum(axis=1)).ravel())
    norms[norms == 0] = 1
    return sparse.diags(1 / norms) @ m
