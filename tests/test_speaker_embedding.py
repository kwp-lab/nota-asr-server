import numpy as np
import pytest

from nota_asr_server.backends.speaker_embedding import SpeakerEmbeddingBackend


def test_normalize_embedding_flattens_and_l2_normalizes():
    vector = SpeakerEmbeddingBackend._normalize_result(
        [{"spk_embedding": np.asarray([[3.0, 4.0]], dtype=np.float32)}]
    )

    assert vector == pytest.approx((0.6, 0.8))


@pytest.mark.parametrize(
    "raw",
    [[], [{}], [{"spk_embedding": []}], [{"spk_embedding": [0.0, 0.0]}]],
)
def test_normalize_embedding_rejects_invalid_vectors(raw):
    with pytest.raises(ValueError):
        SpeakerEmbeddingBackend._normalize_result(raw)
