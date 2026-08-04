from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections import namedtuple
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from nota_asr_server.backends.base import (
    AlignedToken,
    BackendResult,
    BackendSegment,
    BackendWindowResult,
    SpeakerTraceChunk,
)
from nota_asr_server.config import Settings
from nota_asr_server.main import create_app
from nota_asr_server.schemas import CreateTranscriptionJob
from nota_asr_server.services import batch_jobs
from nota_asr_server.services.batch_jobs import (
    BatchJobService,
    BatchJobStore,
    JobRecord,
    WindowRecord,
)


class FakeBatchModelManager:
    ready = True
    loaded_models = ["sensevoice"]
    readiness_detail = None

    def preload(self):
        return None

    def list_models(self):
        return []

    def transcribe_window(
        self,
        model,
        audio_path,
        *,
        language,
        diarization,
        duration,
    ):
        assert Path(audio_path).is_file()
        return BackendWindowResult(
            result=BackendResult(
                text="会议开始。",
                language="zh",
                duration=duration,
                processing_time=0.25,
                segments=(
                    BackendSegment(
                        start=0.0,
                        end=min(duration, 0.1),
                        text="会议开始。",
                        speaker="speaker_0" if diarization else None,
                    ),
                ),
            ),
            speaker_centers=((1.0, 0.0),) if diarization else (),
        )

    def cluster_speaker_centers(self, model, centers, *, speaker_count):
        return tuple(0 for _ in centers)


def settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "model_dir": tmp_path / "models",
        "data_dir": tmp_path / "data",
        "batch_upload_chunk_bytes": 1024,
        "batch_window_seconds": 1,
        "batch_window_overlap_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


def ogg_bytes(tmp_path: Path, *, seconds: float = 0.2) -> bytes:
    path = tmp_path / "meeting.ogg"
    sample_rate = 48_000
    frames = max(round(sample_rate * seconds), 1)
    samples = np.sin(np.arange(frames, dtype=np.float32) * 0.01) * 0.1
    sf.write(path, samples, sample_rate, format="OGG", subtype="OPUS")
    return path.read_bytes()


def create_payload(size: int, *, model: str = "sensevoice") -> dict:
    return {
        "file_name": "meeting.ogg",
        "content_type": "audio/ogg",
        "size_bytes": size,
        "model": model,
        "language": "auto",
        "response_format": "verbose_json",
        "diarization": True,
    }


def test_store_adds_turn_alignment_columns_to_existing_window_table(tmp_path):
    configured = settings(tmp_path)
    configured.data_dir.mkdir(parents=True)
    connection = sqlite3.connect(configured.data_dir / "nota-asr.sqlite3")
    connection.execute(
        """
        CREATE TABLE transcription_job_windows (
          job_id TEXT NOT NULL,
          window_index INTEGER NOT NULL,
          start_seconds REAL NOT NULL,
          end_seconds REAL NOT NULL,
          result_json TEXT NOT NULL,
          speaker_centers_json TEXT NOT NULL,
          completed_at TEXT NOT NULL,
          PRIMARY KEY(job_id, window_index)
        )
        """
    )
    connection.commit()
    connection.close()

    store = BatchJobStore(configured)
    try:
        columns = {
            row[1]
            for row in store._connection.execute(
                "PRAGMA table_info(transcription_job_windows)"
            ).fetchall()
        }
        assert {"speaker_trace_blob", "aligned_tokens_json"} <= columns
    finally:
        store.close()


def wait_for_state(client: TestClient, job_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body = client.get(f"/v1/nota/transcription-jobs/{job_id}").json()
        if body["state"] == expected:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {expected}: {body}")


@pytest.mark.parametrize("model", ["sensevoice", "fun-asr-nano"])
def test_resumable_batch_protocol_returns_existing_verbose_schema(tmp_path, model):
    audio = ogg_bytes(tmp_path)
    app = create_app(
        settings=settings(tmp_path),
        model_manager=FakeBatchModelManager(),
    )
    with TestClient(app) as client:
        capabilities = client.get("/v1/nota/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["batch_transcription_version"] == "1"

        first = client.post(
            "/v1/nota/transcription-jobs",
            headers={"Idempotency-Key": "recording-1-generation-1"},
            json=create_payload(len(audio), model=model),
        )
        repeated = client.post(
            "/v1/nota/transcription-jobs",
            headers={"Idempotency-Key": "recording-1-generation-1"},
            json=create_payload(len(audio), model=model),
        )
        assert first.status_code == 201
        assert repeated.json()["id"] == first.json()["id"]
        job_id = first.json()["id"]

        offset = 0
        while offset < len(audio):
            chunk = audio[offset : offset + 1024]
            response = client.patch(
                f"/v1/nota/transcription-jobs/{job_id}/audio",
                headers={
                    "Upload-Offset": str(offset),
                    "Upload-Checksum": f"sha256={hashlib.sha256(chunk).hexdigest()}",
                    "Content-Type": "application/offset+octet-stream",
                },
                content=chunk,
            )
            assert response.status_code == 204
            offset = int(response.headers["upload-offset"])

        queued = client.post(f"/v1/nota/transcription-jobs/{job_id}/complete")
        assert queued.status_code == 202
        wait_for_state(client, job_id, "succeeded")

        result = client.get(f"/v1/nota/transcription-jobs/{job_id}/result")
        assert result.status_code == 200
        assert result.json() == {
            "schema_version": "1.0",
            "task": "transcribe",
            "model": model,
            "language": "zh",
            "duration": result.json()["duration"],
            "processing_time": 0.25,
            "text": "会议开始。",
            "segments": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 0.1,
                    "text": "会议开始。",
                    "speaker": "speaker_0",
                }
            ],
        }

        deleted = client.delete(f"/v1/nota/transcription-jobs/{job_id}")
        assert deleted.status_code == 204
        assert client.get(f"/v1/nota/transcription-jobs/{job_id}").status_code == 404


def test_upload_offset_and_checksum_errors_are_recoverable(tmp_path):
    audio = ogg_bytes(tmp_path)
    app = create_app(settings=settings(tmp_path), model_manager=FakeBatchModelManager())
    with TestClient(app) as client:
        created = client.post(
            "/v1/nota/transcription-jobs",
            headers={"Idempotency-Key": "offset-test"},
            json=create_payload(len(audio)),
        )
        job_id = created.json()["id"]
        chunk = audio[:512]

        bad_checksum = client.patch(
            f"/v1/nota/transcription-jobs/{job_id}/audio",
            headers={
                "Upload-Offset": "0",
                "Upload-Checksum": f"sha256={'0' * 64}",
            },
            content=chunk,
        )
        assert bad_checksum.status_code == 422
        assert bad_checksum.json()["error"]["code"] == "upload_checksum_mismatch"

        accepted = client.patch(
            f"/v1/nota/transcription-jobs/{job_id}/audio",
            headers={
                "Upload-Offset": "0",
                "Upload-Checksum": f"sha256={hashlib.sha256(chunk).hexdigest()}",
            },
            content=chunk,
        )
        assert accepted.status_code == 204

        conflict = client.patch(
            f"/v1/nota/transcription-jobs/{job_id}/audio",
            headers={
                "Upload-Offset": "0",
                "Upload-Checksum": f"sha256={hashlib.sha256(chunk).hexdigest()}",
            },
            content=chunk,
        )
        assert conflict.status_code == 409
        assert conflict.headers["upload-offset"] == str(len(chunk))

        incomplete = client.post(f"/v1/nota/transcription-jobs/{job_id}/complete")
        assert incomplete.status_code == 409
        assert incomplete.json()["error"]["code"] == "upload_incomplete"


def test_complete_rejects_invalid_ogg_and_duration_over_limit(tmp_path):
    configured = settings(tmp_path, max_audio_seconds=1)
    app = create_app(settings=configured, model_manager=FakeBatchModelManager())
    with TestClient(app) as client:
        invalid = b"not-an-ogg-file"
        created = client.post(
            "/v1/nota/transcription-jobs",
            headers={"Idempotency-Key": "invalid-ogg"},
            json=create_payload(len(invalid)),
        )
        invalid_id = created.json()["id"]
        uploaded = client.patch(
            f"/v1/nota/transcription-jobs/{invalid_id}/audio",
            headers={
                "Upload-Offset": "0",
                "Upload-Checksum": f"sha256={hashlib.sha256(invalid).hexdigest()}",
            },
            content=invalid,
        )
        assert uploaded.status_code == 204
        rejected = client.post(f"/v1/nota/transcription-jobs/{invalid_id}/complete")
        assert rejected.status_code == 415
        assert rejected.json()["error"]["code"] == "unsupported_audio"

        long_audio = ogg_bytes(tmp_path, seconds=1.2)
        created = client.post(
            "/v1/nota/transcription-jobs",
            headers={"Idempotency-Key": "too-long"},
            json=create_payload(len(long_audio)),
        )
        long_id = created.json()["id"]
        offset = 0
        while offset < len(long_audio):
            chunk = long_audio[offset : offset + 1024]
            response = client.patch(
                f"/v1/nota/transcription-jobs/{long_id}/audio",
                headers={
                    "Upload-Offset": str(offset),
                    "Upload-Checksum": f"sha256={hashlib.sha256(chunk).hexdigest()}",
                },
                content=chunk,
            )
            assert response.status_code == 204
            offset = int(response.headers["upload-offset"])
        rejected = client.post(f"/v1/nota/transcription-jobs/{long_id}/complete")
        assert rejected.status_code == 413
        assert rejected.json()["error"]["code"] == "audio_too_long"


def test_create_reports_insufficient_disk_space_before_upload(tmp_path, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        batch_jobs.shutil,
        "disk_usage",
        lambda _path: usage(100, 99, 1),
    )
    app = create_app(settings=settings(tmp_path), model_manager=FakeBatchModelManager())
    with TestClient(app) as client:
        rejected = client.post(
            "/v1/nota/transcription-jobs",
            headers={"Idempotency-Key": "disk-full"},
            json=create_payload(100),
        )
        assert rejected.status_code == 507
        assert rejected.json()["error"]["code"] == "insufficient_storage"


def test_upload_offset_survives_service_restart(tmp_path):
    configured = settings(tmp_path)
    manager = FakeBatchModelManager()
    audio = ogg_bytes(tmp_path)
    service = BatchJobService(configured, manager)
    request = CreateTranscriptionJob.model_validate(create_payload(len(audio)))
    job = service.create("anonymous", "restart-upload", request)
    chunk = audio[:512]
    service.upload(
        "anonymous",
        job.id,
        offset=0,
        checksum=f"sha256={hashlib.sha256(chunk).hexdigest()}",
        content=chunk,
    )
    service.store.close()

    restarted = BatchJobService(configured, manager)
    try:
        recovered = restarted.status("anonymous", job.id)
        assert recovered.upload_offset == len(chunk)
        assert restarted.store.source_path(job.id).stat().st_size == len(chunk)
    finally:
        restarted.store.close()


def test_cancelled_upload_can_resume_at_committed_offset(tmp_path):
    configured = settings(tmp_path)
    service = BatchJobService(configured, FakeBatchModelManager())
    try:
        audio = ogg_bytes(tmp_path)
        request = CreateTranscriptionJob.model_validate(create_payload(len(audio)))
        job = service.create("anonymous", "cancel-resume", request)
        chunk = audio[:256]
        service.upload(
            "anonymous",
            job.id,
            offset=0,
            checksum=f"sha256={hashlib.sha256(chunk).hexdigest()}",
            content=chunk,
        )
        assert service.cancel("anonymous", job.id).state == "cancelled"
        resumed = service.resume("anonymous", job.id)
        assert resumed.state == "uploading"
        assert resumed.upload_offset == len(chunk)
    finally:
        service.store.close()


def test_voiced_audio_without_complete_speaker_centroids_fails_explicitly(tmp_path):
    class MissingCentroidManager(FakeBatchModelManager):
        def transcribe_window(self, model, audio_path, *, language, diarization, duration):
            return BackendWindowResult(
                result=BackendResult(
                    text="有语音。",
                    language="zh",
                    duration=duration,
                    processing_time=0.1,
                    segments=(BackendSegment(0.0, duration, "有语音。", None),),
                ),
                speaker_centers=(),
            )

    audio = ogg_bytes(tmp_path)
    app = create_app(settings=settings(tmp_path), model_manager=MissingCentroidManager())
    with TestClient(app) as client:
        created = client.post(
            "/v1/nota/transcription-jobs",
            headers={"Idempotency-Key": "missing-centroid"},
            json=create_payload(len(audio)),
        )
        job_id = created.json()["id"]
        offset = 0
        while offset < len(audio):
            chunk = audio[offset : offset + 1024]
            response = client.patch(
                f"/v1/nota/transcription-jobs/{job_id}/audio",
                headers={
                    "Upload-Offset": str(offset),
                    "Upload-Checksum": f"sha256={hashlib.sha256(chunk).hexdigest()}",
                },
                content=chunk,
            )
            assert response.status_code == 204
            offset = int(response.headers["upload-offset"])
        client.post(f"/v1/nota/transcription-jobs/{job_id}/complete")
        failed = wait_for_state(client, job_id, "failed")
        assert failed["error"]["code"] == "diarization_failed"


def test_silent_audio_may_return_an_empty_diarized_result(tmp_path):
    class SilentManager(FakeBatchModelManager):
        def transcribe_window(self, model, audio_path, *, language, diarization, duration):
            return BackendWindowResult(
                result=BackendResult(
                    text="",
                    language="und",
                    duration=duration,
                    processing_time=0.1,
                    segments=(),
                ),
                speaker_centers=(),
            )

    audio = ogg_bytes(tmp_path)
    app = create_app(settings=settings(tmp_path), model_manager=SilentManager())
    with TestClient(app) as client:
        created = client.post(
            "/v1/nota/transcription-jobs",
            headers={"Idempotency-Key": "silent"},
            json=create_payload(len(audio)),
        )
        job_id = created.json()["id"]
        offset = 0
        while offset < len(audio):
            chunk = audio[offset : offset + 1024]
            response = client.patch(
                f"/v1/nota/transcription-jobs/{job_id}/audio",
                headers={
                    "Upload-Offset": str(offset),
                    "Upload-Checksum": f"sha256={hashlib.sha256(chunk).hexdigest()}",
                },
                content=chunk,
            )
            offset = int(response.headers["upload-offset"])
        client.post(f"/v1/nota/transcription-jobs/{job_id}/complete")
        wait_for_state(client, job_id, "succeeded")
        result = client.get(f"/v1/nota/transcription-jobs/{job_id}/result").json()
        assert result["language"] == "und"
        assert result["text"] == ""
        assert result["segments"] == []


def test_jobs_are_scoped_to_authenticated_principal(tmp_path):
    configured = settings(tmp_path, api_keys=("first", "second"))
    app = create_app(settings=configured, model_manager=FakeBatchModelManager())
    audio = ogg_bytes(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/v1/nota/transcription-jobs",
            headers={
                "Authorization": "Bearer first",
                "Idempotency-Key": "private-job",
            },
            json=create_payload(len(audio)),
        )
        job_id = created.json()["id"]
        hidden = client.get(
            f"/v1/nota/transcription-jobs/{job_id}",
            headers={"Authorization": "Bearer second"},
        )
        assert hidden.status_code == 404


def test_global_clustering_reconciles_swapped_local_labels(tmp_path):
    class ClusterManager(FakeBatchModelManager):
        def cluster_speaker_centers(self, model, centers, *, speaker_count):
            assert model == "fun-asr-nano"
            assert centers == ((1.0, 0.0), (0.0, 1.0), (0.0, 1.0), (1.0, 0.0))
            assert speaker_count == 2
            time.sleep(0.01)
            return (7, 9, 9, 7)

    service = BatchJobService(settings(tmp_path), ClusterManager())
    try:
        job = JobRecord(
            id="job",
            owner="anonymous",
            idempotency_key="key",
            state="processing",
            phase="diarizing",
            file_name="meeting.ogg",
            content_type="audio/ogg",
            upload_length=100,
            upload_offset=100,
            model="fun-asr-nano",
            language="auto",
            diarization=True,
            speaker_count=2,
            duration=4.0,
            progress_current=2,
            progress_total=2,
            progress_unit="windows",
            result_json=None,
            error_code=None,
            error_message=None,
            cancel_requested=False,
            expires_at="2099-01-01T00:00:00Z",
        )
        windows = (
            WindowRecord(
                index=0,
                start=0.0,
                end=2.0,
                result=BackendResult(
                    text="甲乙",
                    language="zh",
                    duration=2.0,
                    processing_time=0.2,
                    segments=(
                        BackendSegment(0.0, 0.8, "甲", "speaker_0"),
                        BackendSegment(1.0, 1.8, "乙", "speaker_1"),
                    ),
                ),
                speaker_centers=((1.0, 0.0), (0.0, 1.0)),
            ),
            WindowRecord(
                index=1,
                start=2.0,
                end=4.0,
                result=BackendResult(
                    text="乙甲",
                    language="zh",
                    duration=2.0,
                    processing_time=0.3,
                    segments=(
                        BackendSegment(0.0, 0.8, "乙", "speaker_0"),
                        BackendSegment(1.0, 1.8, "甲", "speaker_1"),
                    ),
                ),
                speaker_centers=((0.0, 1.0), (1.0, 0.0)),
            ),
        )

        result = service._finalize(job, windows)

        assert [segment.speaker for segment in result.segments] == [
            "speaker_0",
            "speaker_1",
            "speaker_1",
            "speaker_0",
        ]
        assert [segment.id for segment in result.segments] == [0, 1, 2, 3]
        assert result.processing_time >= 0.51
    finally:
        service.store.close()


def test_finalization_splits_a_vad_segment_with_meeting_wide_speaker_turns(tmp_path):
    class TurnClusterManager(FakeBatchModelManager):
        def cluster_speaker_centers(self, model, centers, *, speaker_count):
            assert speaker_count == 3
            return tuple(range(len(centers)))

    service = BatchJobService(settings(tmp_path), TurnClusterManager())
    try:
        stored_job = service.store.create(
            "anonymous",
            "key",
            CreateTranscriptionJob.model_validate(create_payload(100)),
            model="sensevoice",
        )
        job = JobRecord(
            id=stored_job.id,
            owner="anonymous",
            idempotency_key="key",
            state="processing",
            phase="diarizing",
            file_name="meeting.ogg",
            content_type="audio/ogg",
            upload_length=100,
            upload_offset=100,
            model="sensevoice",
            language="auto",
            diarization=True,
            speaker_count=3,
            duration=3.0,
            progress_current=1,
            progress_total=1,
            progress_unit="windows",
            result_json=None,
            error_code=None,
            error_message=None,
            cancel_requested=False,
            expires_at="2099-01-01T00:00:00Z",
        )
        trace = (
            SpeakerTraceChunk(0.0, 1.0, 0, (1.0, 0.0, 0.0)),
            SpeakerTraceChunk(1.0, 2.0, 1, (0.0, 1.0, 0.0)),
            SpeakerTraceChunk(2.0, 3.0, 2, (0.0, 0.0, 1.0)),
        )
        window = WindowRecord(
            index=0,
            start=0.0,
            end=3.0,
            result=BackendResult(
                text="甲乙丙",
                language="zh",
                duration=3.0,
                processing_time=0.1,
                segments=(BackendSegment(0.0, 3.0, "甲乙丙", "speaker_0"),),
            ),
            speaker_centers=(
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            speaker_trace=trace,
            aligned_tokens=(
                AlignedToken(0.1, 0.8, "甲"),
                AlignedToken(1.1, 1.8, "乙"),
                AlignedToken(2.1, 2.8, "丙"),
            ),
        )

        service.store.save_window(job.id, window)
        restored = service.store.windows(job.id)[0]
        result = service._finalize(job, (restored,))

        assert [segment.text for segment in result.segments] == ["甲", "乙", "丙"]
        assert [segment.speaker for segment in result.segments] == [
            "speaker_0",
            "speaker_1",
            "speaker_2",
        ]
        assert result.text.replace("\n", "") == "甲乙丙"
        assert len(restored.speaker_trace) == 3
        assert [token.text for token in restored.aligned_tokens] == ["甲", "乙", "丙"]
    finally:
        service.store.close()


def test_overlap_midpoint_keeps_each_utterance_once(tmp_path):
    service = BatchJobService(settings(tmp_path), FakeBatchModelManager())
    try:
        job = JobRecord(
            id="overlap",
            owner="anonymous",
            idempotency_key="key",
            state="processing",
            phase="diarizing",
            file_name="meeting.ogg",
            content_type="audio/ogg",
            upload_length=100,
            upload_offset=100,
            model="sensevoice",
            language="auto",
            diarization=False,
            speaker_count=None,
            duration=6.0,
            progress_current=2,
            progress_total=2,
            progress_unit="windows",
            result_json=None,
            error_code=None,
            error_message=None,
            cancel_requested=False,
            expires_at="2099-01-01T00:00:00Z",
        )
        windows = (
            WindowRecord(
                index=0,
                start=0.0,
                end=4.0,
                result=BackendResult(
                    text="前段 重复旧",
                    language="zh",
                    duration=4.0,
                    processing_time=0.1,
                    segments=(
                        BackendSegment(0.0, 1.0, "前段", None),
                        BackendSegment(2.8, 3.2, "重复旧", None),
                    ),
                ),
                speaker_centers=(),
            ),
            WindowRecord(
                index=1,
                start=2.0,
                end=6.0,
                result=BackendResult(
                    text="重复新 后段",
                    language="zh",
                    duration=4.0,
                    processing_time=0.1,
                    segments=(
                        BackendSegment(0.8, 1.2, "重复新", None),
                        BackendSegment(2.0, 3.0, "后段", None),
                    ),
                ),
                speaker_centers=(),
            ),
        )

        result = service._finalize(job, windows)

        assert [segment.text for segment in result.segments] == ["前段", "重复新", "后段"]
        assert [segment.id for segment in result.segments] == [0, 1, 2]
    finally:
        service.store.close()


def test_cancel_during_inference_persists_the_completed_window(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class BlockingManager(FakeBatchModelManager):
        def transcribe_window(self, *args, **kwargs):
            started.set()
            assert release.wait(timeout=5)
            return super().transcribe_window(*args, **kwargs)

    configured = settings(tmp_path)
    service = BatchJobService(configured, BlockingManager())
    audio = ogg_bytes(tmp_path, seconds=1.2)
    request = CreateTranscriptionJob.model_validate(create_payload(len(audio)))
    job = service.create("anonymous", "cancel-active", request)
    offset = 0
    while offset < len(audio):
        chunk = audio[offset : offset + configured.batch_upload_chunk_bytes]
        service.upload(
            "anonymous",
            job.id,
            offset=offset,
            checksum=f"sha256={hashlib.sha256(chunk).hexdigest()}",
            content=chunk,
        )
        offset += len(chunk)
    service.start()
    try:
        service.complete("anonymous", job.id)
        assert started.wait(timeout=5)
        service.cancel("anonymous", job.id)
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with service._active_lock:
                if job.id not in service._active:
                    break
            time.sleep(0.02)
        assert len(service.store.windows(job.id)) == 1
        assert service.status("anonymous", job.id).state == "cancelled"
    finally:
        release.set()
        service.stop()


def test_processing_rows_are_requeued_after_restart(tmp_path):
    configured = settings(tmp_path)
    store = BatchJobStore(configured)
    try:
        request = CreateTranscriptionJob.model_validate(create_payload(100))
        job = store.create("anonymous", "processing-recovery", request, model="sensevoice")
        store.source_path(job.id).write_bytes(b"x" * 100)
        store.commit_upload_offset(job.id, 100)
        store.queue(job.id, duration=2.0, total_windows=2)
        assert store.begin_processing(job.id).state == "processing"
        store.save_window(
            job.id,
            WindowRecord(
                index=0,
                start=0.0,
                end=1.0,
                result=BackendResult(
                    text="done",
                    language="en",
                    duration=1.0,
                    processing_time=0.1,
                    segments=(BackendSegment(0.0, 1.0, "done", "speaker_0"),),
                ),
                speaker_centers=((1.0, 0.0),),
            ),
        )
        store.set_phase(job.id, "diarizing", current=0, total=1, unit="steps")
    finally:
        store.close()

    restarted = BatchJobStore(configured)
    try:
        assert restarted.recover_queued() == (job.id,)
        recovered = restarted.get(job.id)
        assert recovered.state == "queued"
        assert recovered.progress_current == 1
        assert recovered.progress_total == 2
        assert recovered.progress_unit == "windows"
        assert [window.index for window in restarted.windows(job.id)] == [0]
    finally:
        restarted.close()


def test_resume_after_diarization_cancel_restores_window_progress(tmp_path):
    configured = settings(tmp_path)
    store = BatchJobStore(configured)
    try:
        request = CreateTranscriptionJob.model_validate(create_payload(100))
        job = store.create("anonymous", "resume-finalize", request, model="sensevoice")
        store.source_path(job.id).write_bytes(b"x" * 100)
        store.commit_upload_offset(job.id, 100)
        store.queue(job.id, duration=2.0, total_windows=2)
        assert store.begin_processing(job.id).state == "processing"
        store.set_phase(job.id, "diarizing", current=0, total=1, unit="steps")
        store.cancel(job.id)

        resumed = store.resume(job.id)

        assert resumed.state == "queued"
        assert resumed.progress_total == 2
        assert resumed.progress_unit == "windows"
    finally:
        store.close()


def test_expired_jobs_remove_database_rows_and_audio(tmp_path):
    store = BatchJobStore(settings(tmp_path))
    try:
        assert store._connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
        request = CreateTranscriptionJob.model_validate(create_payload(100))
        job = store.create("anonymous", "expired", request, model="sensevoice")
        with store._lock:
            store._connection.execute(
                "UPDATE transcription_jobs SET expires_at = '2000-01-01T00:00:00Z' WHERE id = ?",
                (job.id,),
            )
            store._connection.commit()
        assert store.cleanup_expired() == 1
        assert not store.job_dir(job.id).exists()
        try:
            store.get(job.id)
        except Exception as error:
            assert getattr(error, "code", None) == "job_not_found"
        else:
            raise AssertionError("expired job still exists")
    finally:
        store.close()
