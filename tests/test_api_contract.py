import io
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nota_asr_server.backends.base import BackendResult, BackendSegment
from nota_asr_server.backends.speaker_embedding import (
    CleanSpeakerRange,
    SpeakerSampleAnalysis,
)
from nota_asr_server.config import Settings
from nota_asr_server.errors import UnknownModelError
from nota_asr_server.main import create_app


class FakeModelManager:
    def __init__(self):
        self.ready = True
        self.loaded_models = ["sensevoice"]
        self.readiness_detail = None
        self.captured_path: str | None = None
        self.captured_embedding_path: str | None = None
        self.captured_sample_paths: list[str] = []

    def preload(self):
        return None

    def list_models(self):
        return [
            {
                "id": "sensevoice",
                "object": "model",
                "owned_by": "nota",
                "ready": True,
                "capabilities": {
                    "languages": ["zh", "en", "ja", "ko", "yue"],
                    "diarization": True,
                    "decoder_hotwords": False,
                },
            },
            {
                "id": "fun-asr-nano",
                "object": "model",
                "owned_by": "nota",
                "ready": False,
                "capabilities": {
                    "languages": ["zh", "en", "ja", "yue"],
                    "diarization": True,
                    "decoder_hotwords": False,
                },
            },
        ]

    def extract_speaker_embedding(self, audio_path):
        self.captured_embedding_path = audio_path
        assert Path(audio_path).exists()
        return (0.6, 0.8)

    def analyze_speaker_samples(self, audio_paths):
        self.captured_sample_paths = list(audio_paths)
        assert all(Path(path).exists() for path in audio_paths)
        return SpeakerSampleAnalysis(
            outcome="enrollable",
            embedding=(0.6, 0.8),
            audio_duration=10.0,
            accepted_audio_duration=8.0,
            purity_score=0.91,
            ranges=(CleanSpeakerRange(0, 0.5, 4.5), CleanSpeakerRange(1, 1.0, 5.0)),
            preview=CleanSpeakerRange(0, 0.5, 4.5),
        )

    def transcribe(
        self,
        model,
        audio_path,
        *,
        language,
        diarization,
        speaker_count,
        duration,
    ):
        if model == "missing":
            raise UnknownModelError(model)
        self.captured_path = audio_path
        assert Path(audio_path).exists()
        return BackendResult(
            text="会议开始。",
            language="zh",
            duration=9.25,
            processing_time=0.44,
            segments=(
                BackendSegment(
                    start=0.5,
                    end=2.5,
                    text="会议开始。",
                    speaker="speaker_0" if diarization else None,
                ),
            ),
        )


def make_pcm16_wav(seconds=5, *, sample_rate=16_000, channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * sample_rate * seconds * channels)
    return output.getvalue()


def make_client(*, api_keys=()):
    settings = Settings(api_keys=tuple(api_keys))
    manager = FakeModelManager()
    return TestClient(create_app(settings=settings, model_manager=manager)), manager


@pytest.mark.parametrize("model", ["sensevoice", "fun-asr-nano"])
def test_verbose_json_contract_and_temp_file_cleanup(model):
    client, manager = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"not-real-audio", "audio/wav")},
            data={
                "model": model,
                "language": "zh",
                "response_format": "verbose_json",
                "diarization": "true",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.json() == {
        "schema_version": "1.0",
        "task": "transcribe",
        "model": model,
        "language": "zh",
        "duration": 9.25,
        "processing_time": 0.44,
        "text": "会议开始。",
        "segments": [
            {
                "id": 0,
                "start": 0.5,
                "end": 2.5,
                "text": "会议开始。",
                "speaker": "speaker_0",
            }
        ],
    }
    assert manager.captured_path is not None
    assert not Path(manager.captured_path).exists()


def test_compact_json_stays_openai_compatible():
    client, _ = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"audio", "audio/wav")},
            data={"response_format": "json"},
        )

    assert response.status_code == 200
    assert response.json() == {"text": "会议开始。"}


def test_api_key_boundary():
    client, _ = make_client(api_keys=("secret-key",))
    with client:
        missing = client.get("/v1/models")
        accepted = client.get(
            "/v1/models", headers={"Authorization": "Bearer secret-key"}
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "invalid_api_key"
    assert accepted.status_code == 200


def test_models_endpoint_advertises_nano_capabilities():
    client, _ = make_client()
    with client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    models = {item["id"]: item for item in response.json()["data"]}
    assert models["fun-asr-nano"]["ready"] is False
    assert models["fun-asr-nano"]["capabilities"] == {
        "languages": ["zh", "en", "ja", "yue"],
        "diarization": True,
        "decoder_hotwords": False,
    }


def test_errors_use_the_stable_envelope():
    client, _ = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"audio", "audio/wav")},
            data={"model": "missing", "response_format": "verbose_json"},
        )

    body = response.json()
    assert response.status_code == 400
    assert set(body) == {"error"}
    assert body["error"]["code"] == "model_not_found"
    assert body["error"]["request_id"] == response.headers["x-request-id"]


def test_health_and_readiness_do_not_require_authentication():
    client, _ = make_client(api_keys=("secret-key",))
    with client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["service"] == "nota-asr-server"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_unsupported_extension_is_rejected_before_inference():
    client, _ = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.txt", b"audio", "text/plain")},
        )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_audio"


def test_nota_capabilities_advertise_speaker_embedding_contract():
    client, _ = make_client()
    with client:
        response = client.get("/v1/nota/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["speaker_embedding_version"] == "1"
    assert body["speaker_embedding_min_seconds"] == 5
    assert body["speaker_embedding_max_seconds"] == 30
    assert body["speaker_embedding_max_bytes"] == 2 * 1024 * 1024
    assert body["speaker_sample_analysis_version"] == "1"
    assert body["speaker_sample_analysis_max_files"] == 8
    assert body["speaker_sample_analysis_min_clip_seconds"] == 3
    assert body["speaker_sample_analysis_max_clip_seconds"] == 12
    assert body["speaker_sample_analysis_max_total_seconds"] == 30
    assert body["speaker_sample_analysis_min_accepted_seconds"] == 5
    assert body["speaker_sample_analysis_min_purity"] == 0.70


def test_speaker_embedding_contract_and_temp_file_cleanup():
    client, manager = make_client()
    with client:
        response = client.post(
            "/v1/nota/speaker-embeddings",
            files={"file": ("speaker.wav", make_pcm16_wav(), "audio/wav")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "schema_version": "1",
        "embedding_model": "cam++",
        "embedding_fingerprint": (
            "cam++:iic/speech_campplus_sv_zh-cn_16k-common:v1"
        ),
        "dimension": 2,
        "audio_duration": 5.0,
        "embedding": [0.6, 0.8],
    }
    assert manager.captured_embedding_path is not None
    assert not Path(manager.captured_embedding_path).exists()


@pytest.mark.parametrize(
    ("seconds", "sample_rate", "channels", "expected_code"),
    [
        (4, 16_000, 1, "voice_sample_too_short"),
        (5, 8_000, 1, "invalid_voice_sample"),
        (5, 16_000, 2, "invalid_voice_sample"),
    ],
)
def test_speaker_embedding_rejects_invalid_samples(
    seconds, sample_rate, channels, expected_code
):
    client, manager = make_client()
    audio = make_pcm16_wav(
        seconds,
        sample_rate=sample_rate,
        channels=channels,
    )
    with client:
        response = client.post(
            "/v1/nota/speaker-embeddings",
            files={"file": ("speaker.wav", audio, "audio/wav")},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == expected_code
    assert manager.captured_embedding_path is None


def test_speaker_embedding_requires_api_key():
    client, _ = make_client(api_keys=("secret-key",))
    with client:
        rejected = client.post(
            "/v1/nota/speaker-embeddings",
            files={"file": ("speaker.wav", make_pcm16_wav(), "audio/wav")},
        )
        accepted = client.post(
            "/v1/nota/speaker-embeddings",
            headers={"Authorization": "Bearer secret-key"},
            files={"file": ("speaker.wav", make_pcm16_wav(), "audio/wav")},
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_speaker_sample_analysis_contract_and_cleanup():
    client, manager = make_client()
    files = [
        ("files", ("candidate-0.wav", make_pcm16_wav(), "audio/wav")),
        ("files", ("candidate-1.wav", make_pcm16_wav(), "audio/wav")),
    ]
    with client:
        response = client.post("/v1/nota/speaker-samples/analyze", files=files)

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1",
        "outcome": "enrollable",
        "embedding_model": "cam++",
        "embedding_fingerprint": (
            "cam++:iic/speech_campplus_sv_zh-cn_16k-common:v1"
        ),
        "dimension": 2,
        "audio_duration": 10.0,
        "accepted_audio_duration": 8.0,
        "purity_score": 0.91,
        "preview": {"file_index": 0, "start": 0.5, "end": 4.5},
        "accepted_ranges": [
            {"file_index": 0, "start": 0.5, "end": 4.5},
            {"file_index": 1, "start": 1.0, "end": 5.0},
        ],
        "embedding": [0.6, 0.8],
    }
    assert manager.captured_sample_paths
    assert all(not Path(path).exists() for path in manager.captured_sample_paths)


def test_speaker_sample_analysis_returns_preview_only_without_retaining_files():
    client, manager = make_client()

    def preview_only(audio_paths):
        manager.captured_sample_paths = list(audio_paths)
        return SpeakerSampleAnalysis(
            outcome="preview_only",
            embedding=None,
            audio_duration=5.0,
            accepted_audio_duration=0.0,
            purity_score=0.42,
            ranges=(),
            preview=CleanSpeakerRange(0, 0.5, 4.5),
        )

    manager.analyze_speaker_samples = preview_only
    with client:
        response = client.post(
            "/v1/nota/speaker-samples/analyze",
            files={"files": ("candidate.wav", make_pcm16_wav(), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["outcome"] == "preview_only"
    assert response.json()["embedding"] is None
    assert response.json()["dimension"] == 0
    assert response.json()["accepted_ranges"] == []
    assert manager.captured_sample_paths
    assert all(not Path(path).exists() for path in manager.captured_sample_paths)


@pytest.mark.parametrize("seconds", [2, 13])
def test_speaker_sample_analysis_enforces_per_candidate_duration(seconds):
    client, manager = make_client()
    with client:
        response = client.post(
            "/v1/nota/speaker-samples/analyze",
            files={"files": ("candidate.wav", make_pcm16_wav(seconds), "audio/wav")},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_voice_sample_duration"
    assert not manager.captured_sample_paths


def test_speaker_sample_analysis_enforces_candidate_count_and_total_duration():
    client, manager = make_client()
    too_many = [
        ("files", (f"candidate-{index}.wav", make_pcm16_wav(3), "audio/wav"))
        for index in range(9)
    ]
    too_long = [
        ("files", (f"candidate-{index}.wav", make_pcm16_wav(11), "audio/wav"))
        for index in range(3)
    ]
    with client:
        count_response = client.post(
            "/v1/nota/speaker-samples/analyze", files=too_many
        )
        duration_response = client.post(
            "/v1/nota/speaker-samples/analyze", files=too_long
        )

    assert count_response.status_code == 422
    assert count_response.json()["error"]["code"] == "invalid_sample_count"
    assert duration_response.status_code == 413
    assert duration_response.json()["error"]["code"] == "voice_samples_too_long"
    assert not manager.captured_sample_paths


def test_srt_response_exposes_cue_times_and_speaker_labels():
    client, manager = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"audio", "audio/wav")},
            data={"response_format": "srt", "diarization": "true"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-subrip; charset=utf-8"
    assert response.text == (
        "1\n00:00:00,500 --> 00:00:02,500\nspeaker_0: 会议开始。\n"
    )
    assert manager.captured_path is not None
    assert not Path(manager.captured_path).exists()


def test_vtt_response_starts_with_the_webvtt_header():
    client, _ = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"audio", "audio/wav")},
            data={"response_format": "vtt"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/vtt; charset=utf-8"
    assert response.text == (
        "WEBVTT\n\n00:00:00.500 --> 00:00:02.500\nspeaker_0: 会议开始。\n"
    )


def test_text_response_stays_openai_compatible():
    client, _ = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"audio", "audio/wav")},
            data={"response_format": "text"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == "会议开始。"


def test_disabled_diarization_renders_cues_without_speaker_labels():
    client, _ = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"audio", "audio/wav")},
            data={"response_format": "srt", "diarization": "false"},
        )

    assert response.status_code == 200
    assert response.text == "1\n00:00:00,500 --> 00:00:02,500\n会议开始。\n"


def test_unknown_response_format_is_rejected():
    client, _ = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"audio", "audio/wav")},
            data={"response_format": "docx"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_response_format"
