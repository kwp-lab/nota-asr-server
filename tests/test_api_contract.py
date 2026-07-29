from pathlib import Path

from fastapi.testclient import TestClient

from nota_asr_server.backends.base import BackendResult, BackendSegment
from nota_asr_server.config import Settings
from nota_asr_server.errors import UnknownModelError
from nota_asr_server.main import create_app


class FakeModelManager:
    def __init__(self):
        self.ready = True
        self.loaded_models = ["sensevoice"]
        self.readiness_detail = None
        self.captured_path: str | None = None

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
            }
        ]

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


def make_client(*, api_keys=()):
    settings = Settings(api_keys=tuple(api_keys))
    manager = FakeModelManager()
    return TestClient(create_app(settings=settings, model_manager=manager)), manager


def test_verbose_json_contract_and_temp_file_cleanup():
    client, manager = make_client()
    with client:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": ("meeting.wav", b"not-real-audio", "audio/wav")},
            data={
                "model": "sensevoice",
                "response_format": "verbose_json",
                "diarization": "true",
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.json() == {
        "schema_version": "1.0",
        "task": "transcribe",
        "model": "sensevoice",
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

