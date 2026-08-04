import numpy as np
import torch

from nota_asr_server.backends.speaker_clustering import ShortRecordingClusterBackend


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
