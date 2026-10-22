import numpy as np
from scipy import sparse

from shiftnet_backend.discovery.cluster import cluster, nearest
from shiftnet_backend.discovery.encoder import normalize_rows


def _vectors(rng, centre, n, noise=0.15):
    return np.clip(centre + rng.normal(0, noise, (n, len(centre))), 0, None)


def test_two_senses_and_an_outlier():
    rng = np.random.default_rng(0)
    a = np.array([1, 1, 1, 0, 0, 0, 0, 0], float)
    b = np.array([0, 0, 0, 1, 1, 1, 0, 0], float)
    odd = np.array([[0, 0, 0, 0, 0, 0, 1, 1]], float)
    X = normalize_rows(sparse.csr_matrix(np.vstack([_vectors(rng, a, 30), _vectors(rng, b, 12), odd])))
    c = cluster(X, threshold=0.35, min_size=5)
    assert sorted(np.bincount(c.labels[c.labels >= 0]).tolist()) == [12, 30]
    assert c.labels[:30].tolist() == [0] * 30  # largest cluster first
    assert c.labels[-1] == -1  # the outlier stays noise: not similar to either centroid
    assert np.isnan(c.similarity[-1]) and (c.similarity[:-1] > 0.8).all()
    best, score = nearest(c.centroids, normalize_rows(sparse.csr_matrix(np.vstack([b, a]))))
    assert best.tolist() == [1, 0] and (score > 0.9).all()


def test_small_clusters_are_reassigned_when_close_enough():
    rng = np.random.default_rng(1)
    a = np.array([1, 1, 1, 0], float)
    near_a = np.array([[1, 1, 0.2, 0.6]], float)  # its own singleton at a strict threshold
    X = normalize_rows(sparse.csr_matrix(np.vstack([_vectors(rng, a, 10, 0.02), near_a])))
    strict = cluster(X, threshold=0.95, min_size=3, reassign=False)
    assert strict.labels[-1] == -1
    loose = cluster(X, threshold=0.8, min_size=3, reassign=True)
    assert loose.labels[-1] == 0


def test_degenerate_inputs():
    assert cluster(sparse.csr_matrix((0, 4))).labels.size == 0
    one = cluster(normalize_rows(sparse.csr_matrix(np.ones((1, 4)))), min_size=1)
    assert one.labels.tolist() == [0]
