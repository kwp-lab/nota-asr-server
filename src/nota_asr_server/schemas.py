from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptionSegment(StrictModel):
    id: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    speaker: str | None


class CompactTranscription(StrictModel):
    text: str


class VerboseTranscription(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    task: Literal["transcribe"] = "transcribe"
    model: str
    language: str
    duration: float = Field(ge=0)
    processing_time: float = Field(ge=0)
    text: str
    segments: list[TranscriptionSegment]


class ModelCapabilities(StrictModel):
    languages: list[str]
    diarization: bool
    decoder_hotwords: bool


class ModelInfo(StrictModel):
    id: str
    object: Literal["model"] = "model"
    owned_by: Literal["nota"] = "nota"
    ready: bool
    capabilities: ModelCapabilities


class ModelList(StrictModel):
    object: Literal["list"] = "list"
    data: list[ModelInfo]


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: Literal["nota-asr-server"] = "nota-asr-server"
    version: str


class ReadyResponse(StrictModel):
    status: Literal["ready", "not_ready"]
    device: str
    preload_model: str
    models_loaded: list[str]
    detail: str | None = None


class ErrorDetail(StrictModel):
    type: str
    code: str
    message: str
    request_id: str


class ErrorEnvelope(StrictModel):
    error: ErrorDetail


class BatchCapabilities(StrictModel):
    batch_transcription_version: Literal["1"] = "1"
    upload_chunk_bytes: int = Field(gt=0)
    max_upload_bytes: int = Field(gt=0)
    max_audio_seconds: int = Field(gt=0)
    audio_formats: list[Literal["ogg"]]


class CreateTranscriptionJob(StrictModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_type: Literal["audio/ogg", "application/ogg"] = "audio/ogg"
    size_bytes: int = Field(gt=0)
    model: str | None = None
    language: str = Field(default="auto", min_length=1, max_length=32)
    response_format: Literal["verbose_json"] = "verbose_json"
    diarization: bool = True
    speaker_count: int | None = Field(default=None, ge=1, le=64)


class JobFailure(StrictModel):
    code: str
    message: str


class TranscriptionJobStatus(StrictModel):
    id: str
    state: Literal[
        "uploading",
        "queued",
        "processing",
        "succeeded",
        "failed",
        "cancelled",
    ]
    phase: Literal[
        "uploading",
        "queued",
        "transcribing",
        "diarizing",
        "finalizing",
        "completed",
        "failed",
        "cancelled",
    ]
    upload_offset: int = Field(ge=0)
    upload_length: int = Field(gt=0)
    progress_current: int = Field(ge=0)
    progress_total: int = Field(ge=0)
    progress_unit: Literal["bytes", "windows", "steps"]
    expires_at: str
    error: JobFailure | None = None
