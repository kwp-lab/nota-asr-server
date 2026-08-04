import numpy as np
import torch

from nota_asr_server.backends.speaker_clustering import (
    ShortRecordingClusterBackend,
    cluster_meeting_speaker_centers,
)


class UpstreamCluster:
    def __init__(self):
        self.calls = []

    def __call__(self, embeddings, *, oracle_num=None):
        self.calls.append((embeddings, oracle_num))
        return np.full(embeddings.shape[0], 7, dtype=int)


def test_short_recording_uses_known_speaker_count():
    upstream = UpstreamCluster()
    backend = ShortRecordingClusterBackend(upstream)
    embeddings = torch.tensor(
        [
            [1.0, 0.0],
            [0.95, 0.05],
            [0.0, 1.0],
            [0.05, 0.95],
        ]
    )

    labels = backend(embeddings, oracle_num=2)

    assert len(set(labels)) == 2
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert not upstream.calls


def test_short_recording_estimates_speakers_from_cosine_similarity():
    upstream = UpstreamCluster()
    backend = ShortRecordingClusterBackend(upstream, merge_threshold=0.78)
    embeddings = torch.tensor(
        [
            [1.0, 0.0],
            [0.98, 0.02],
            [0.0, 1.0],
            [0.02, 0.98],
        ]
    )

    labels = backend(embeddings)

    assert len(set(labels)) == 2
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]


def test_long_recording_delegates_to_funasr_cluster_backend():
    upstream = UpstreamCluster()
    backend = ShortRecordingClusterBackend(upstream)
    embeddings = torch.ones((20, 2))

    labels = backend(embeddings, oracle_num=3)

    assert labels.tolist() == [7] * 20
    assert upstream.calls == [(embeddings, 3)]


def test_long_recording_bounds_requested_speakers_by_embedding_count():
    upstream = UpstreamCluster()
    backend = ShortRecordingClusterBackend(upstream)
    embeddings = torch.ones((20, 2))

    backend(embeddings, oracle_num=64)

    assert upstream.calls == [(embeddings, 20)]


def test_requested_speaker_count_is_bounded_by_embedding_count():
    backend = ShortRecordingClusterBackend(UpstreamCluster())
    embeddings = torch.tensor([[1.0, 0.0], [0.0, 1.0]])

    labels = backend(embeddings, oracle_num=5)

    assert len(set(labels)) == 2


def test_zero_embedding_does_not_crash_short_recording_clustering():
    backend = ShortRecordingClusterBackend(UpstreamCluster())
    embeddings = torch.tensor([[0.0, 0.0], [1.0, 0.0], [0.99, 0.01]])

    labels = backend(embeddings)

    assert labels.shape == (3,)
    assert labels[1] == labels[2]


def test_cluster_capture_is_single_use_and_can_be_cleared():
    backend = ShortRecordingClusterBackend(UpstreamCluster())
    embeddings = torch.tensor([[1.0, 0.0], [0.0, 1.0]])

    labels = backend(embeddings, oracle_num=2)
    capture = backend.take_capture()

    assert capture is not None
    assert np.array_equal(capture.labels, labels)
    assert np.array_equal(capture.embeddings, embeddings.numpy())
    assert backend.take_capture() is None

    backend(embeddings, oracle_num=2)
    backend.clear_capture()
    assert backend.take_capture() is None


def test_meeting_centers_use_deterministic_threshold_clustering_above_twenty():
    first_speaker = np.asarray(
        [[1.0, value, 0.0] for value in np.linspace(0.0, 0.08, 12)],
        dtype=np.float32,
    )
    second_speaker = np.asarray(
        [[value, 1.0, 0.0] for value in np.linspace(0.0, 0.08, 11)],
        dtype=np.float32,
    )
    centers = np.vstack((first_speaker, second_speaker))

    first = cluster_meeting_speaker_centers(centers, speaker_count=None)
    second = cluster_meeting_speaker_centers(centers, speaker_count=None)

    assert centers.shape[0] == 23
    assert np.array_equal(first, second)
    assert len(set(first.tolist())) == 2
    assert first[0] != first[-1]


def test_known_meeting_speaker_count_is_bounded_by_available_centers():
    centers = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    labels = cluster_meeting_speaker_centers(centers, speaker_count=64)

    assert len(set(labels.tolist())) == 2


def test_known_eight_speakers_are_deterministic_with_twenty_three_centers():
    groups = []
    for speaker in range(8):
        count = 2 if speaker == 7 else 3
        for variation in range(count):
            center = np.zeros(8, dtype=np.float32)
            center[speaker] = 1.0
            center[(speaker + 1) % 8] = variation * 0.02
            groups.append(center)
    centers = np.asarray(groups, dtype=np.float32)

    first = cluster_meeting_speaker_centers(centers, speaker_count=8)
    second = cluster_meeting_speaker_centers(centers, speaker_count=8)

    assert centers.shape[0] == 23
    assert np.array_equal(first, second)
    assert len(set(first.tolist())) == 8
    assert first[0] != first[3]


def test_known_speaker_count_uses_the_same_safety_line_as_automatic_mode():
    centers = np.asarray(
        [
            [1.0, 0.0],
            [0.70, np.sqrt(1.0 - 0.70**2)],
        ],
        dtype=np.float32,
    )

    automatic = cluster_meeting_speaker_centers(centers, speaker_count=None)
    specified = cluster_meeting_speaker_centers(centers, speaker_count=1)

    assert len(set(automatic.tolist())) == 2
    assert len(set(specified.tolist())) == 2
    assert specified[0] != specified[1]


def test_known_speaker_count_can_return_more_safe_clusters_than_requested():
    centers = np.eye(9, dtype=np.float32)

    labels = cluster_meeting_speaker_centers(centers, speaker_count=8)

    assert len(set(labels.tolist())) == 9


def test_known_speaker_count_splits_safe_clusters_up_to_the_target():
    centers = np.asarray(
        [
            [1.0, 0.00],
            [1.0, 0.02],
            [1.0, 0.04],
            [1.0, 0.06],
        ],
        dtype=np.float32,
    )

    labels = cluster_meeting_speaker_centers(centers, speaker_count=3)

    assert len(set(labels.tolist())) == 3


def test_automatic_meeting_clusters_cannot_chain_weakly_related_centers():
    centers = np.asarray(
        [
            [1.0, 0.0],
            [0.8, 0.6],
            [0.28, 0.96],
        ],
        dtype=np.float32,
    )

    labels = cluster_meeting_speaker_centers(
        centers,
        speaker_count=None,
        merge_threshold=0.78,
    )

    assert labels[0] == labels[1]
    assert labels[0] != labels[2]
