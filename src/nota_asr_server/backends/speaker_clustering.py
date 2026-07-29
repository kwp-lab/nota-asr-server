from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering


class ShortRecordingClusterBackend:
    """Use FunASR clustering normally, but retain diarization for small inputs."""

    def __init__(self, upstream: Any, *, merge_threshold: float = 0.78) -> None:
        self._upstream = upstream
        self._merge_threshold = merge_threshold

    def __call__(self, embeddings: Any, *, oracle_num: int | None = None) -> np.ndarray:
        sample_count = int(embeddings.shape[0])
        if sample_count >= 20:
            return self._upstream(embeddings, oracle_num=oracle_num)
        if sample_count == 0:
            return np.empty(0, dtype=int)
        if sample_count == 1:
            return np.zeros(1, dtype=int)

        matrix = embeddings.detach().cpu().numpy().astype(float, copy=False)
        matrix = np.nan_to_num(matrix, copy=False)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        normalized = np.divide(
            matrix,
            norms,
            out=np.zeros_like(matrix),
            where=norms > 0,
        )
        cosine_distances = np.clip(1.0 - normalized @ normalized.T, 0.0, 2.0)
        np.fill_diagonal(cosine_distances, 0.0)
        requested_speakers = None
        if oracle_num is not None:
            requested_speakers = max(1, min(int(oracle_num), sample_count))

        if requested_speakers == 1:
            return np.zeros(sample_count, dtype=int)
        if requested_speakers is not None:
            cluster = AgglomerativeClustering(
                n_clusters=requested_speakers,
                metric="precomputed",
                linkage="average",
            )
        else:
            cluster = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=1.0 - self._merge_threshold,
                metric="precomputed",
                linkage="average",
            )
        return cluster.fit_predict(cosine_distances).astype(int, copy=False)
