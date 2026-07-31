from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from nota_asr_server.backends.base import BackendResult, BackendSegment
from nota_asr_server.config import Settings
from nota_asr_server.errors import APIError, ModelLoadError, UnknownModelError
from nota_asr_server.schemas import (
    CreateTranscriptionJob,
    JobFailure,
    TranscriptionJobStatus,
    TranscriptionSegment,
    VerboseTranscription,
)


logger = logging.getLogger("nota_asr_server.batch")
TARGET_SAMPLE_RATE = 16_000
MIN_WORKSPACE_RESERVE_BYTES = 16 * 1024 * 1024


class DiarizationFailedError(Exception):
    pass


@dataclass(frozen=True)
class JobRecord:
    id: str
    owner: str
    idempotency_key: str
    state: str
    phase: str
    file_name: str
    content_type: str
    upload_length: int
    upload_offset: int
    model: str
    language: str
    diarization: bool
    speaker_count: int | None
    duration: float | None
    progress_current: int
    progress_total: int
    progress_unit: str
    result_json: str | None
    error_code: str | None
    error_message: str | None
    cancel_requested: bool
    expires_at: str


@dataclass(frozen=True)
class WindowRecord:
    index: int
    start: float
    end: float
    result: BackendResult
    speaker_centers: tuple[tuple[float, ...], ...]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _window_count(duration: float, window_seconds: int, overlap_seconds: int) -> int:
    if duration <= window_seconds:
        return 1
    stride = window_seconds - overlap_seconds
    return 1 + math.ceil((duration - window_seconds) / stride)


class BatchJobStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.data_dir = settings.data_dir
        self.jobs_dir = self.data_dir / "jobs"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.data_dir / "nota-asr.sqlite3",
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA secure_delete=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS transcription_jobs (
              id TEXT PRIMARY KEY,
              owner TEXT NOT NULL,
              idempotency_key TEXT NOT NULL,
              state TEXT NOT NULL,
              phase TEXT NOT NULL,
              file_name TEXT NOT NULL,
              content_type TEXT NOT NULL,
              upload_length INTEGER NOT NULL,
              upload_offset INTEGER NOT NULL DEFAULT 0,
              model TEXT NOT NULL,
              language TEXT NOT NULL,
              diarization INTEGER NOT NULL,
              speaker_count INTEGER,
              duration REAL,
              progress_current INTEGER NOT NULL DEFAULT 0,
              progress_total INTEGER NOT NULL DEFAULT 0,
              progress_unit TEXT NOT NULL,
              result_json TEXT,
              error_code TEXT,
              error_message TEXT,
              cancel_requested INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              UNIQUE(owner, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS transcription_job_windows (
              job_id TEXT NOT NULL REFERENCES transcription_jobs(id) ON DELETE CASCADE,
              window_index INTEGER NOT NULL,
              start_seconds REAL NOT NULL,
              end_seconds REAL NOT NULL,
              result_json TEXT NOT NULL,
              speaker_centers_json TEXT NOT NULL,
              completed_at TEXT NOT NULL,
              PRIMARY KEY(job_id, window_index)
            );
            """
        )
        self._recover_disk_offsets()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def source_path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "source.ogg"

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def create(
        self,
        owner: str,
        idempotency_key: str,
        request: CreateTranscriptionJob,
        *,
        model: str,
    ) -> JobRecord:
        now = _utc_now()
        expires = _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds))
        with self._lock:
            existing = self._connection.execute(
                """
                SELECT * FROM transcription_jobs
                WHERE owner = ? AND idempotency_key = ?
                """,
                (owner, idempotency_key),
            ).fetchone()
            if existing is not None:
                job = self._row_to_job(existing)
                if (
                    job.file_name != Path(request.file_name).name
                    or job.upload_length != request.size_bytes
                    or job.model != model
                    or job.language != request.language
                    or job.diarization != request.diarization
                    or job.speaker_count != request.speaker_count
                ):
                    raise APIError(
                        409,
                        "idempotency_conflict",
                        "Idempotency-Key was already used for different job parameters",
                    )
                return job

            job_id = uuid.uuid4().hex
            directory = self.job_dir(job_id)
            directory.mkdir(parents=True, exist_ok=False)
            self.source_path(job_id).touch(exist_ok=False)
            timestamp = _iso(now)
            try:
                self._connection.execute(
                    """
                    INSERT INTO transcription_jobs (
                      id, owner, idempotency_key, state, phase, file_name,
                      content_type, upload_length, upload_offset, model, language,
                      diarization, speaker_count, progress_current, progress_total,
                      progress_unit, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, 'uploading', 'uploading', ?, ?, ?, 0, ?, ?, ?, ?,
                              0, ?, 'bytes', ?, ?, ?)
                    """,
                    (
                        job_id,
                        owner,
                        idempotency_key,
                        Path(request.file_name).name,
                        request.content_type,
                        request.size_bytes,
                        model,
                        request.language,
                        int(request.diarization),
                        request.speaker_count,
                        request.size_bytes,
                        timestamp,
                        timestamp,
                        expires,
                    ),
                )
                self._connection.commit()
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            return self.get(job_id, owner)

    def get(self, job_id: str, owner: str | None = None) -> JobRecord:
        with self._lock:
            if owner is None:
                row = self._connection.execute(
                    "SELECT * FROM transcription_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT * FROM transcription_jobs WHERE id = ? AND owner = ?",
                    (job_id, owner),
                ).fetchone()
        if row is None:
            raise APIError(404, "job_not_found", "Transcription job was not found")
        return self._row_to_job(row)

    def find_by_idempotency(self, owner: str, idempotency_key: str) -> JobRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM transcription_jobs
                WHERE owner = ? AND idempotency_key = ?
                """,
                (owner, idempotency_key),
            ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def refresh_expiry(self, job_id: str) -> None:
        now = _utc_now()
        with self._lock:
            self._connection.execute(
                "UPDATE transcription_jobs SET updated_at = ?, expires_at = ? WHERE id = ?",
                (
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            )
            self._connection.commit()

    def reserved_upload_bytes(self) -> int:
        with self._lock:
            value = self._connection.execute(
                """
                SELECT COALESCE(SUM(upload_length - upload_offset), 0)
                FROM transcription_jobs
                WHERE upload_offset < upload_length
                """
            ).fetchone()[0]
        return max(int(value), 0)

    def commit_upload_offset(self, job_id: str, offset: int) -> JobRecord:
        now = _utc_now()
        with self._lock:
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET upload_offset = ?, progress_current = ?, updated_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    offset,
                    offset,
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            )
            self._connection.commit()
        return self.get(job_id)

    def queue(self, job_id: str, duration: float, total_windows: int) -> JobRecord:
        now = _utc_now()
        with self._lock:
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET state = 'queued', phase = 'queued', duration = ?,
                    progress_current = (
                      SELECT COUNT(*) FROM transcription_job_windows WHERE job_id = ?
                    ),
                    progress_total = ?, progress_unit = 'windows',
                    cancel_requested = 0, error_code = NULL, error_message = NULL,
                    updated_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    duration,
                    job_id,
                    total_windows,
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            )
            self._connection.commit()
        return self.get(job_id)

    def begin_processing(self, job_id: str) -> JobRecord | None:
        now = _utc_now()
        with self._lock:
            changed = self._connection.execute(
                """
                UPDATE transcription_jobs
                SET state = 'processing', phase = 'transcribing', cancel_requested = 0,
                    updated_at = ?, expires_at = ?
                WHERE id = ? AND state = 'queued'
                """,
                (
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            ).rowcount
            self._connection.commit()
        return self.get(job_id) if changed else None

    def save_window(self, job_id: str, window: WindowRecord) -> None:
        payload = {
            "text": window.result.text,
            "language": window.result.language,
            "duration": window.result.duration,
            "processing_time": window.result.processing_time,
            "segments": [asdict(segment) for segment in window.result.segments],
        }
        now = _utc_now()
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO transcription_job_windows (
                  job_id, window_index, start_seconds, end_seconds, result_json,
                  speaker_centers_json, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    window.index,
                    window.start,
                    window.end,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(window.speaker_centers),
                    _iso(now),
                ),
            )
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET progress_current = (
                  SELECT COUNT(*) FROM transcription_job_windows WHERE job_id = ?
                ), updated_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    job_id,
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            )
            self._connection.commit()

    def windows(self, job_id: str) -> tuple[WindowRecord, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM transcription_job_windows
                WHERE job_id = ? ORDER BY window_index
                """,
                (job_id,),
            ).fetchall()
        records: list[WindowRecord] = []
        for row in rows:
            payload = json.loads(row["result_json"])
            records.append(
                WindowRecord(
                    index=int(row["window_index"]),
                    start=float(row["start_seconds"]),
                    end=float(row["end_seconds"]),
                    result=BackendResult(
                        text=str(payload["text"]),
                        language=str(payload["language"]),
                        duration=float(payload["duration"]),
                        processing_time=float(payload["processing_time"]),
                        segments=tuple(
                            BackendSegment(
                                start=float(segment["start"]),
                                end=float(segment["end"]),
                                text=str(segment["text"]),
                                speaker=segment.get("speaker"),
                            )
                            for segment in payload["segments"]
                        ),
                    ),
                    speaker_centers=tuple(
                        tuple(float(value) for value in center)
                        for center in json.loads(row["speaker_centers_json"])
                    ),
                )
            )
        return tuple(records)

    def set_phase(
        self,
        job_id: str,
        phase: str,
        *,
        current: int,
        total: int,
        unit: str,
    ) -> None:
        now = _utc_now()
        with self._lock:
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET phase = ?, progress_current = ?, progress_total = ?,
                    progress_unit = ?, updated_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    phase,
                    current,
                    total,
                    unit,
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            )
            self._connection.commit()

    def succeed(self, job_id: str, result_json: str) -> None:
        now = _utc_now()
        with self._lock:
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET state = 'succeeded', phase = 'completed', result_json = ?,
                    progress_current = 1, progress_total = 1, progress_unit = 'steps',
                    error_code = NULL, error_message = NULL, cancel_requested = 0,
                    updated_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    result_json,
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            )
            self._connection.commit()

    def fail(self, job_id: str, code: str, message: str) -> None:
        now = _utc_now()
        with self._lock:
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET state = 'failed', phase = 'failed', error_code = ?, error_message = ?,
                    cancel_requested = 0, updated_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    code,
                    message,
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            )
            self._connection.commit()

    def cancel(self, job_id: str) -> JobRecord:
        now = _utc_now()
        with self._lock:
            self._connection.execute(
                """
                UPDATE transcription_jobs
                SET state = 'cancelled', phase = 'cancelled', cancel_requested = 1,
                    error_code = NULL, error_message = NULL, updated_at = ?, expires_at = ?
                WHERE id = ? AND state NOT IN ('succeeded', 'cancelled')
                """,
                (
                    _iso(now),
                    _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                    job_id,
                ),
            )
            self._connection.commit()
        return self.get(job_id)

    def resume(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job.state not in {"cancelled", "failed"}:
            if job.state in {"uploading", "queued", "processing", "succeeded"}:
                return job
            raise APIError(409, "job_state_conflict", "Job cannot be resumed")
        if job.upload_offset < job.upload_length:
            now = _utc_now()
            with self._lock:
                self._connection.execute(
                    """
                    UPDATE transcription_jobs
                    SET state = 'uploading', phase = 'uploading',
                        progress_current = upload_offset, progress_total = upload_length,
                        progress_unit = 'bytes', cancel_requested = 0,
                        error_code = NULL, error_message = NULL,
                        updated_at = ?, expires_at = ?
                    WHERE id = ?
                    """,
                    (
                        _iso(now),
                        _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                        job_id,
                    ),
                )
                self._connection.commit()
            return self.get(job_id)
        if job.duration is None:
            now = _utc_now()
            with self._lock:
                self._connection.execute(
                    """
                    UPDATE transcription_jobs
                    SET state = 'uploading', phase = 'uploading',
                        progress_current = upload_offset, progress_total = upload_length,
                        progress_unit = 'bytes', cancel_requested = 0,
                        error_code = NULL, error_message = NULL,
                        updated_at = ?, expires_at = ?
                    WHERE id = ?
                    """,
                    (
                        _iso(now),
                        _iso(now + timedelta(seconds=self.settings.batch_job_retention_seconds)),
                        job_id,
                    ),
                )
                self._connection.commit()
            return self.get(job_id)
        total_windows = _window_count(
            job.duration,
            self.settings.batch_window_seconds,
            self.settings.batch_window_overlap_seconds,
        )
        return self.queue(job_id, job.duration, total_windows)

    def recover_queued(self) -> tuple[str, ...]:
        now = _utc_now()
        with self._lock:
            processing = self._connection.execute(
                """
                SELECT id, duration FROM transcription_jobs
                WHERE state = 'processing'
                """
            ).fetchall()
            for row in processing:
                duration = float(row["duration"])
                total_windows = _window_count(
                    duration,
                    self.settings.batch_window_seconds,
                    self.settings.batch_window_overlap_seconds,
                )
                self._connection.execute(
                    """
                    UPDATE transcription_jobs
                    SET state = 'queued', phase = 'queued', cancel_requested = 0,
                        progress_current = (
                          SELECT COUNT(*) FROM transcription_job_windows WHERE job_id = ?
                        ),
                        progress_total = ?, progress_unit = 'windows',
                        updated_at = ?, expires_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(row["id"]),
                        total_windows,
                        _iso(now),
                        _iso(
                            now
                            + timedelta(
                                seconds=self.settings.batch_job_retention_seconds
                            )
                        ),
                        str(row["id"]),
                    ),
                )
            rows = self._connection.execute(
                "SELECT id FROM transcription_jobs WHERE state = 'queued'"
            ).fetchall()
            self._connection.commit()
        return tuple(str(row["id"]) for row in rows)

    def delete(self, job_id: str, owner: str | None = None) -> None:
        job = self.get(job_id, owner)
        directory = self.job_dir(job.id)
        if directory.exists():
            shutil.rmtree(directory)
        with self._lock:
            self._connection.execute(
                "DELETE FROM transcription_jobs WHERE id = ?",
                (job.id,),
            )
            self._connection.commit()
            self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def cleanup_expired(self, *, exclude: set[str] | None = None) -> int:
        excluded = exclude or set()
        now = _iso(_utc_now())
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id FROM transcription_jobs
                WHERE expires_at <= ?
                  AND state IN ('uploading', 'succeeded', 'failed', 'cancelled')
                """,
                (now,),
            ).fetchall()
        removed = 0
        for row in rows:
            job_id = str(row["id"])
            if job_id in excluded:
                continue
            try:
                self.delete(job_id)
                removed += 1
            except APIError:
                pass
        return removed

    def _recover_disk_offsets(self) -> None:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, state, upload_offset FROM transcription_jobs"
            ).fetchall()
        for row in rows:
            path = self.source_path(str(row["id"]))
            committed = int(row["upload_offset"])
            if not path.exists():
                if str(row["state"]) == "succeeded":
                    continue
                self.fail(
                    str(row["id"]),
                    "source_missing",
                    "Uploaded audio is no longer available",
                )
                continue
            actual = path.stat().st_size
            if actual > committed:
                with path.open("r+b") as handle:
                    handle.truncate(committed)
            elif actual < committed:
                with self._lock:
                    self._connection.execute(
                        """
                        UPDATE transcription_jobs
                        SET upload_offset = ?, progress_current = ?
                        WHERE id = ?
                        """,
                        (actual, actual, str(row["id"])),
                    )
                    self._connection.commit()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=str(row["id"]),
            owner=str(row["owner"]),
            idempotency_key=str(row["idempotency_key"]),
            state=str(row["state"]),
            phase=str(row["phase"]),
            file_name=str(row["file_name"]),
            content_type=str(row["content_type"]),
            upload_length=int(row["upload_length"]),
            upload_offset=int(row["upload_offset"]),
            model=str(row["model"]),
            language=str(row["language"]),
            diarization=bool(row["diarization"]),
            speaker_count=(
                int(row["speaker_count"]) if row["speaker_count"] is not None else None
            ),
            duration=float(row["duration"]) if row["duration"] is not None else None,
            progress_current=int(row["progress_current"]),
            progress_total=int(row["progress_total"]),
            progress_unit=str(row["progress_unit"]),
            result_json=row["result_json"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            cancel_requested=bool(row["cancel_requested"]),
            expires_at=str(row["expires_at"]),
        )


class BatchJobService:
    def __init__(self, settings: Settings, model_manager: Any) -> None:
        self.settings = settings
        self.model_manager = model_manager
        self.store = BatchJobStore(settings)
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self._active_lock = threading.RLock()
        self._active: set[str] = set()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        if self._worker is not None:
            return
        self.store.cleanup_expired()
        for job_id in self.store.recover_queued():
            self._queue.put(job_id)
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="nota-batch-worker",
            daemon=True,
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        if self._worker is not None:
            # A running inference cannot be interrupted safely. Let the current
            # bounded window finish and persist it before closing SQLite.
            self._worker.join()
        self.store.close()

    def create(
        self,
        owner: str,
        idempotency_key: str,
        request: CreateTranscriptionJob,
    ) -> JobRecord:
        if not idempotency_key or len(idempotency_key) > 128:
            raise APIError(
                422,
                "invalid_idempotency_key",
                "Idempotency-Key must contain 1 to 128 characters",
            )
        if Path(request.file_name).suffix.lower() != ".ogg":
            raise APIError(
                415,
                "unsupported_audio",
                "Nota batch jobs accept Ogg audio only",
            )
        if request.size_bytes > self.settings.max_upload_bytes:
            raise APIError(413, "upload_too_large", "The uploaded file exceeds the size limit")
        model = request.model or self.settings.preload_model
        if model not in self.settings.enabled_models:
            raise APIError(400, "model_not_found", f"Unknown model: {model}")
        if self.store.find_by_idempotency(owner, idempotency_key) is not None:
            return self.store.create(
                owner,
                idempotency_key,
                request,
                model=model,
            )
        self._require_free_disk(
            request.size_bytes + self.store.reserved_upload_bytes(),
            "There is not enough disk space to accept this recording",
        )
        return self.store.create(owner, idempotency_key, request, model=model)

    def upload(
        self,
        owner: str,
        job_id: str,
        *,
        offset: int,
        checksum: str,
        content: bytes,
    ) -> JobRecord:
        job = self.store.get(job_id, owner)
        if job.state != "uploading":
            raise APIError(409, "job_state_conflict", "Job is not accepting audio")
        if offset != job.upload_offset:
            raise APIError(
                409,
                "upload_offset_mismatch",
                "Upload-Offset does not match the committed server offset",
                headers={"Upload-Offset": str(job.upload_offset)},
            )
        if not content:
            raise APIError(400, "empty_upload_chunk", "Upload chunk must not be empty")
        if len(content) > self.settings.batch_upload_chunk_bytes:
            raise APIError(413, "upload_chunk_too_large", "Upload chunk exceeds the size limit")
        if offset + len(content) > job.upload_length:
            raise APIError(413, "upload_too_large", "Upload exceeds the declared file size")
        expected = self._parse_checksum(checksum)
        actual = hashlib.sha256(content).hexdigest()
        if not secrets.compare_digest(actual, expected):
            raise APIError(422, "upload_checksum_mismatch", "Upload chunk checksum is invalid")

        path = self.store.source_path(job_id)
        with path.open("r+b") as handle:
            handle.seek(offset)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return self.store.commit_upload_offset(job_id, offset + len(content))

    def complete(self, owner: str, job_id: str) -> JobRecord:
        job = self.store.get(job_id, owner)
        if job.state in {"queued", "processing", "succeeded"}:
            return job
        if job.state != "uploading":
            raise APIError(409, "job_state_conflict", "Job cannot be finalized")
        if job.upload_offset != job.upload_length:
            raise APIError(409, "upload_incomplete", "Audio upload is not complete")

        path = self.store.source_path(job.id)
        try:
            info = sf.info(path)
        except Exception as exc:
            raise APIError(415, "unsupported_audio", "Uploaded Ogg audio is invalid") from exc
        if info.format != "OGG":
            raise APIError(415, "unsupported_audio", "Uploaded audio is not an Ogg container")
        duration = max(float(info.duration), 0.0)
        if duration <= 0:
            raise APIError(400, "empty_audio", "Uploaded audio has no decodable samples")
        if duration > self.settings.max_audio_seconds:
            raise APIError(
                413,
                "audio_too_long",
                f"Audio duration exceeds the {self.settings.max_audio_seconds} second limit",
            )
        processing_workspace = (
            self.settings.batch_window_seconds * TARGET_SAMPLE_RATE * 2
            + self.settings.batch_upload_chunk_bytes
        )
        self._require_free_disk(
            processing_workspace,
            "There is not enough disk space to process this recording",
        )
        total = _window_count(
            duration,
            self.settings.batch_window_seconds,
            self.settings.batch_window_overlap_seconds,
        )
        job = self.store.queue(job.id, duration, total)
        self._queue.put(job.id)
        return job

    def status(self, owner: str, job_id: str) -> JobRecord:
        return self.store.get(job_id, owner)

    def cancel(self, owner: str, job_id: str) -> JobRecord:
        job = self.store.get(job_id, owner)
        if job.state == "succeeded":
            return job
        return self.store.cancel(job.id)

    def resume(self, owner: str, job_id: str) -> JobRecord:
        job = self.store.get(job_id, owner)
        with self._active_lock:
            if job.id in self._active:
                raise APIError(
                    409,
                    "job_still_stopping",
                    "Job is still stopping; retry resume shortly",
                )
        resumed = self.store.resume(job.id)
        if resumed.state == "queued":
            self._queue.put(resumed.id)
        return resumed

    def result(self, owner: str, job_id: str) -> VerboseTranscription:
        job = self.store.get(job_id, owner)
        if job.state != "succeeded" or not job.result_json:
            raise APIError(409, "job_not_ready", "Transcription result is not ready")
        return VerboseTranscription.model_validate_json(job.result_json)

    def delete(self, owner: str, job_id: str) -> None:
        job = self.store.get(job_id, owner)
        with self._active_lock:
            if job.id in self._active:
                raise APIError(409, "job_still_running", "Running job must be cancelled first")
        self.store.delete(job.id, owner)

    def to_status(self, job: JobRecord) -> TranscriptionJobStatus:
        failure = None
        if job.error_code and job.error_message:
            failure = JobFailure(code=job.error_code, message=job.error_message)
        return TranscriptionJobStatus(
            id=job.id,
            state=job.state,  # type: ignore[arg-type]
            phase=job.phase,  # type: ignore[arg-type]
            upload_offset=job.upload_offset,
            upload_length=job.upload_length,
            progress_current=job.progress_current,
            progress_total=job.progress_total,
            progress_unit=job.progress_unit,  # type: ignore[arg-type]
            expires_at=job.expires_at,
            error=failure,
        )

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=60)
            except queue.Empty:
                with self._active_lock:
                    active = set(self._active)
                self.store.cleanup_expired(exclude=active)
                continue
            if job_id is None:
                break
            try:
                self._run_job(job_id)
            except Exception:
                logger.exception("Batch transcription job failed job_id=%s", job_id)
            self.store.cleanup_expired()

    def _run_job(self, job_id: str) -> None:
        job = self.store.begin_processing(job_id)
        if job is None:
            return
        with self._active_lock:
            self._active.add(job_id)
        try:
            completed = {window.index for window in self.store.windows(job_id)}
            for index in range(job.progress_total):
                if self._cancelled(job_id):
                    return
                if index in completed:
                    continue
                window = self._transcribe_window(job, index)
                self.store.save_window(job_id, window)
                if self._cancelled(job_id):
                    return

            if self._cancelled(job_id):
                return
            self.store.set_phase(job_id, "diarizing", current=0, total=1, unit="steps")
            result = self._finalize(job, self.store.windows(job_id))
            if self._cancelled(job_id):
                return
            self.store.set_phase(job_id, "finalizing", current=0, total=1, unit="steps")
            self.store.succeed(job_id, result.model_dump_json())
        except UnknownModelError:
            self.store.fail(job_id, "model_not_found", "The configured model is unavailable")
        except ModelLoadError:
            self.store.fail(job_id, "model_unavailable", "The configured model could not be loaded")
        except DiarizationFailedError:
            self.store.fail(
                job_id,
                "diarization_failed",
                "Speaker diarization could not produce reliable meeting-wide labels",
            )
        except Exception:
            logger.exception("Batch processing failed job_id=%s model=%s", job_id, job.model)
            self.store.fail(
                job_id,
                "processing_failed",
                "The server could not process the recording",
            )
        finally:
            with self._active_lock:
                self._active.discard(job_id)

    def _transcribe_window(self, job: JobRecord, index: int) -> WindowRecord:
        assert job.duration is not None
        stride = (
            self.settings.batch_window_seconds
            - self.settings.batch_window_overlap_seconds
        )
        start = index * stride
        expected_end = min(start + self.settings.batch_window_seconds, job.duration)
        source = self.store.source_path(job.id)
        temp_path = self.store.job_dir(job.id) / f"window-{index}.wav"
        try:
            with sf.SoundFile(source) as audio:
                source_start = round(start * audio.samplerate)
                source_frames = max(round((expected_end - start) * audio.samplerate), 1)
                audio.seek(source_start)
                samples = audio.read(source_frames, dtype="float32", always_2d=True)
                if samples.size == 0:
                    raise ValueError("Audio window contains no samples")
                mono = samples.mean(axis=1, dtype=np.float32)
                if audio.samplerate != TARGET_SAMPLE_RATE:
                    divisor = math.gcd(audio.samplerate, TARGET_SAMPLE_RATE)
                    mono = resample_poly(
                        mono,
                        TARGET_SAMPLE_RATE // divisor,
                        audio.samplerate // divisor,
                    ).astype(np.float32, copy=False)
            actual_duration = len(mono) / TARGET_SAMPLE_RATE
            sf.write(temp_path, mono, TARGET_SAMPLE_RATE, subtype="PCM_16", format="WAV")
            window_result = self.model_manager.transcribe_window(
                job.model,
                str(temp_path),
                language=job.language,
                diarization=job.diarization,
                duration=actual_duration,
            )
            if job.diarization and window_result.result.text:
                voiced_segments = [
                    segment
                    for segment in window_result.result.segments
                    if segment.text.strip()
                ]
                speakers = {
                    segment.speaker
                    for segment in voiced_segments
                    if segment.speaker is not None
                }
                if (
                    not voiced_segments
                    or any(segment.speaker is None for segment in voiced_segments)
                    or not speakers
                    or len(window_result.speaker_centers) < len(speakers)
                ):
                    raise DiarizationFailedError
            return WindowRecord(
                index=index,
                start=float(start),
                end=round(float(start) + actual_duration, 3),
                result=window_result.result,
                speaker_centers=window_result.speaker_centers,
            )
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _finalize(
        self,
        job: JobRecord,
        windows: tuple[WindowRecord, ...],
    ) -> VerboseTranscription:
        finalization_started = time.perf_counter()
        if len(windows) != job.progress_total:
            raise ValueError("Not all transcription windows are available")

        center_keys: list[tuple[int, int]] = []
        centers: list[tuple[float, ...]] = []
        if job.diarization:
            for window in windows:
                for local_index, center in enumerate(window.speaker_centers):
                    center_keys.append((window.index, local_index))
                    centers.append(center)
        if job.diarization and any(window.result.text for window in windows) and not centers:
            raise DiarizationFailedError

        labels = (
            self.model_manager.cluster_speaker_centers(
                job.model,
                tuple(centers),
                speaker_count=job.speaker_count,
            )
            if centers
            else ()
        )
        if len(labels) != len(center_keys):
            raise DiarizationFailedError
        local_to_cluster = dict(zip(center_keys, labels, strict=True))

        text = ""
        merged: list[tuple[float, float, str, int | None]] = []
        cluster_names: dict[int, str] = {}
        language_weights: Counter[str] = Counter()
        processing_time = 0.0
        for position, window in enumerate(windows):
            processing_time += window.result.processing_time
            if window.result.language != "und":
                language_weights[window.result.language] += max(
                    window.end - window.start,
                    0.001,
                )
            lower_boundary = (
                (windows[position - 1].end + window.start) / 2
                if position > 0
                else -math.inf
            )
            upper_boundary = (
                (window.end + windows[position + 1].start) / 2
                if position + 1 < len(windows)
                else math.inf
            )
            for segment in window.result.segments:
                absolute_start = window.start + segment.start
                absolute_end = window.start + segment.end
                midpoint = (absolute_start + absolute_end) / 2
                if midpoint < lower_boundary or midpoint >= upper_boundary:
                    continue
                cluster: int | None = None
                if segment.speaker is not None:
                    try:
                        local_index = int(segment.speaker.removeprefix("speaker_"))
                        cluster = local_to_cluster[(window.index, local_index)]
                    except (KeyError, ValueError) as exc:
                        raise DiarizationFailedError from exc
                    cluster_names.setdefault(cluster, f"speaker_{len(cluster_names)}")
                text = _append_without_overlap(text, segment.text)
                merged.append((absolute_start, absolute_end, segment.text, cluster))

        if not text:
            for window in windows:
                text = _append_without_overlap(text, window.result.text)
        language = (
            job.language
            if job.language != "auto"
            else (language_weights.most_common(1)[0][0] if language_weights else "und")
        )
        assert job.duration is not None
        processing_time += time.perf_counter() - finalization_started
        return VerboseTranscription(
            model=job.model,
            language=language,
            duration=round(job.duration, 3),
            processing_time=round(max(processing_time, 0.0), 3),
            text=text.strip(),
            segments=[
                TranscriptionSegment(
                    id=index,
                    start=round(max(start, 0.0), 3),
                    end=round(max(end, start), 3),
                    text=segment_text,
                    speaker=cluster_names.get(cluster) if cluster is not None else None,
                )
                for index, (start, end, segment_text, cluster) in enumerate(merged)
            ],
        )

    def _require_free_disk(self, required_bytes: int, message: str) -> None:
        available = shutil.disk_usage(self.settings.data_dir).free
        required = max(required_bytes, 0) + MIN_WORKSPACE_RESERVE_BYTES
        if available < required:
            raise APIError(507, "insufficient_storage", message)

    def _cancelled(self, job_id: str) -> bool:
        if self._stop.is_set():
            return True
        try:
            job = self.store.get(job_id)
        except APIError:
            return True
        return job.cancel_requested or job.state == "cancelled"

    @staticmethod
    def _parse_checksum(value: str) -> str:
        prefix = "sha256="
        if not value.startswith(prefix):
            raise APIError(
                422,
                "invalid_upload_checksum",
                "Upload-Checksum must use sha256=<hex>",
            )
        checksum = value[len(prefix) :].lower()
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            raise APIError(
                422,
                "invalid_upload_checksum",
                "Upload-Checksum must use sha256=<hex>",
            )
        return checksum


def _append_without_overlap(output: str, next_text: str) -> str:
    next_text = next_text.strip()
    if not next_text:
        return output
    if not output:
        return next_text
    maximum = min(len(output), len(next_text), 240)
    overlap = next(
        (
            length
            for length in range(maximum, 0, -1)
            if output[-length:] == next_text[:length]
        ),
        0,
    )
    remainder = next_text[overlap:].lstrip()
    if not remainder:
        return output
    separator = "" if overlap else "\n"
    return f"{output}{separator}{remainder}"
