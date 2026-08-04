from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering


@dataclass(frozen=True)
class ClusterCapture:
    embeddings: np.ndarray
    labels: np.ndarray


def cluster_meeting_speaker_centers(
    centers: Any,
    *,
    speaker_count: int | None,
    merge_threshold: float = 0.78,
) -> np.ndarray:
    """Cluster sparse centers while treating a requested count as a safe target."""
    matrix = np.asarray(centers, dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError("Meeting speaker centers must be a two-dimensional matrix")
    sample_count = int(matrix.shape[0])
    if sample_count == 0:
        return np.empty(0, dtype=int)
    requested_speakers = None
    if speaker_count is not None:
        requested_speakers = max(1, min(int(speaker_count), sample_count))
    if sample_count == 1:
        return np.zeros(sample_count, dtype=int)

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
    safe_cluster = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=1.0 - merge_threshold,
        metric="precomputed",
        linkage="complete",
    )
    safe_labels = safe_cluster.fit_predict(cosine_distances).astype(int, copy=False)
    safe_cluster_count = len(set(safe_labels.tolist()))
    if requested_speakers is None or safe_cluster_count >= requested_speakers:
        return safe_labels

    # The safety pass found fewer groups than the user's target. Splitting those
    # groups up to the target cannot combine weakly related voices, while forcing
    # more merges when the safety pass found too many groups would do exactly that.
    target_cluster = AgglomerativeClustering(
        n_clusters=requested_speakers,
        metric="precomputed",
        linkage="complete",
    )
    return target_cluster.fit_predict(cosine_distances).astype(int, copy=False)


class ShortRecordingClusterBackend:
    """Retain short-input diarization and capture the latest cluster input."""

    def __init__(self, upstream: Any, *, merge_threshold: float = 0.78) -> None:
        self._upstream = upstream
        self._merge_threshold = merge_threshold
        self._capture_lock = threading.Lock()
        self._last_capture: ClusterCapture | None = None

    def __call__(self, embeddings: Any, *, oracle_num: int | None = None) -> np.ndarray:
        sample_count = int(embeddings.shape[0])
        requested_speakers = None
        if oracle_num is not None and sample_count > 0:
            requested_speakers = max(1, min(int(oracle_num), sample_count))
        matrix = embeddings.detach().cpu().numpy().astype(np.float32, copy=False)
        matrix = np.nan_to_num(matrix, copy=False)
        if sample_count >= 20:
            labels = self._upstream(embeddings, oracle_num=requested_speakers)
        elif sample_count == 0:
            labels = np.empty(0, dtype=int)
        elif sample_count == 1 or requested_speakers == 1:
            labels = np.zeros(sample_count, dtype=int)
        else:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            normalized = np.divide(
                matrix,
                norms,
                out=np.zeros_like(matrix),
                where=norms > 0,
            )
            cosine_distances = np.clip(1.0 - normalized @ normalized.T, 0.0, 2.0)
            np.fill_diagonal(cosine_distances, 0.0)
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
            labels = cluster.fit_predict(cosine_distances)

        labels_array = np.asarray(labels, dtype=int)
        with self._capture_lock:
            self._last_capture = ClusterCapture(
                embeddings=matrix.copy(),
                labels=labels_array.copy(),
            )
        return labels_array

    def clear_capture(self) -> None:
        with self._capture_lock:
            self._last_capture = None

    def take_capture(self) -> ClusterCapture | None:
        with self._capture_lock:
            capture = self._last_capture
            self._last_capture = None
        return capture
