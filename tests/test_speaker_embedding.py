import numpy as np
import pytest
import soundfile as sf

from nota_asr_server.backends.speaker_embedding import (
    SpeakerEmbeddingBackend,
)


class FakeCamPlus:
    def __init__(self, outputs_by_call):
        self.outputs_by_call = outputs_by_call
        self.calls = 0

    def generate(self, *, input, batch_size):
        assert batch_size == 1
        embeddings = self.outputs_by_call[self.calls]
        assert len(input) == len(embeddings)
        self.calls += 1
        return [
            {"spk_embedding": np.asarray([embedding], dtype=np.float32)}
            for embedding in embeddings
        ]

def write_silence(path, seconds):
    sf.write(path, np.zeros(16_000 * seconds, dtype=np.float32), 16_000, subtype="PCM_16")


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


def test_analysis_aggregates_homogeneous_ranges(tmp_path):
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    write_silence(first, 6)
    write_silence(second, 6)
    # Six-second clips produce seven 1.5 s / 0.75 s CAM++ windows each.
    backend = SpeakerEmbeddingBackend("cpu")
    backend._model = FakeCamPlus(
        [
            [(1.0, 0.0)] * 2,
            [(1.0, 0.0)] * 14,
            [(1.0, 0.0)] * 2,
        ]
    )

    result = backend.analyze([str(first), str(second)])

    assert result.outcome == "enrollable"
    assert result.accepted_audio_duration == pytest.approx(11.0)
    assert result.purity_score == pytest.approx(1.0)
    assert len(result.ranges) == 2
    assert result.preview.file_index == 0
    assert result.preview.start == pytest.approx(0.25)
    assert result.preview.end == pytest.approx(5.75)
    assert result.embedding == pytest.approx((1.0, 0.0))
    assert backend._model.calls == 3


def test_analysis_returns_preview_only_for_mixed_clip(tmp_path):
    clip = tmp_path / "mixed.wav"
    write_silence(clip, 6)
    backend = SpeakerEmbeddingBackend("cpu")
    backend._model = FakeCamPlus(
        [
            [(1.0, 0.0)],
            [(1.0, 0.0)] * 3 + [(0.0, 1.0)] * 4,
        ]
    )

    result = backend.analyze([str(clip)])

    assert result.outcome == "preview_only"
    assert result.embedding is None
    assert result.ranges == ()
    assert result.preview.end > result.preview.start
    assert backend._model.calls == 2


def test_analysis_ignores_an_inconsistent_candidate_before_enrollment(tmp_path):
    paths = [tmp_path / f"candidate-{index}.wav" for index in range(3)]
    for path in paths:
        write_silence(path, 6)
    consistent = (1.0, 0.0)
    contaminant = (0.0, 1.0)
    backend = SpeakerEmbeddingBackend("cpu")
    backend._model = FakeCamPlus(
        [
            [consistent, consistent, contaminant],
            [consistent] * 14 + [contaminant] * 7,
            [consistent] * 2,
        ]
    )

    result = backend.analyze([str(path) for path in paths])

    assert result.outcome == "enrollable"
    assert result.accepted_audio_duration == pytest.approx(11.0)
    assert {item.file_index for item in result.ranges} == {0, 1}
