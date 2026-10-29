"""Grouping usage vectors into candidate senses.

Average-linkage agglomerative clustering on cosine distance, cut at a similarity threshold: two
groups merge while their usages are, on average, at least `threshold` similar. No number of senses
is fixed in advance. LexSPLADE puts same-sense pairs around 0.6–0.9 and different senses around
0.1–0.2, so the default cut of 0.35 sits in the gap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse

from .encoder import normalize_rows

MAX_USAGES = 6000  # the distance matrix is n²; 6000 usages ≈ 290 MB


@dataclass
class Clustering:
    labels: np.ndarray  # per usage: cluster number (0 = largest), or -1 for noise
    centroids: sparse.csr_matrix  # one L2-normalised row per cluster
    similarity: np.ndarray  # per usage: cosine to its centroid (nan for noise)


def cluster(X: sparse.csr_matrix, threshold: float = 0.35, min_size: int = 5, reassign: bool = True) -> Clustering:
    """X: L2-normalised usage vectors. Clusters smaller than min_size become noise; with reassign,
    a noise usage joins the nearest kept cluster when it is at least `threshold` similar to its centroid."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    n = X.shape[0]
    if n > MAX_USAGES:
        raise ValueError(f"{n} usages: cluster at most {MAX_USAGES} (lower the per-dump quota)")
    if n == 0:
        return Clustering(np.empty(0, int), sparse.csr_matrix((0, X.shape[1])), np.empty(0))
    if n == 1:
        raw = np.zeros(1, int)
    else:
        sim = (X @ X.T).toarray()
        dist = np.clip(1 - sim, 0, 2)
        np.fill_diagonal(dist, 0)
        # Average linkage by nearest-neighbour chain: O(n²) time, far quicker than scikit-learn's.
        z = linkage(squareform(dist, checks=False), method="average")
        raw = fcluster(z, t=np.nextafter(1 - threshold, 0), criterion="distance")

    ids, counts = np.unique(raw, return_counts=True)
    kept = [i for i, c in sorted(zip(ids, counts), key=lambda t: -t[1]) if c >= min_size]
    remap = {old: new for new, old in enumerate(kept)}
    labels = np.array([remap.get(r, -1) for r in raw])

    centroids = _centroids(X, labels, len(kept))
    if reassign and len(kept) and (labels == -1).any():
        noise = np.flatnonzero(labels == -1)
        s = (X[noise] @ centroids.T).toarray()
        best = s.argmax(axis=1)
        ok = s[np.arange(len(noise)), best] >= threshold
        labels[noise[ok]] = best[ok]
        centroids = _centroids(X, labels, len(kept))

    similarity = np.full(n, np.nan)
    inside = labels >= 0
    if inside.any():
        similarity[inside] = np.asarray(X[inside].multiply(centroids[labels[inside]]).sum(axis=1)).ravel()
    return Clustering(labels, centroids, similarity)


def _centroids(X: sparse.csr_matrix, labels: np.ndarray, k: int) -> sparse.csr_matrix:
    if k == 0:
        return sparse.csr_matrix((0, X.shape[1]), dtype=X.dtype)
    rows = np.flatnonzero(labels >= 0)
    member = sparse.csr_matrix((np.ones(len(rows)), (labels[rows], rows)), shape=(k, X.shape[0]))
    return normalize_rows(sparse.csr_matrix(member @ X))


def nearest(centroids: sparse.csr_matrix, prototypes: sparse.csr_matrix) -> tuple[np.ndarray, np.ndarray]:
    """For each centroid, the index of the most similar prototype and the similarity."""
    if prototypes.shape[0] == 0 or centroids.shape[0] == 0:
        return np.full(centroids.shape[0], -1), np.full(centroids.shape[0], np.nan)
    s = (centroids @ prototypes.T).toarray()
    best = s.argmax(axis=1)
    return best, s[np.arange(len(best)), best]
