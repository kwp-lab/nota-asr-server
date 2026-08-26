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


class HotwordModelCapabilities(StrictModel):
    supported: bool
    mode: Literal["none", "decoder_bias", "prompt"]
    max_entries: int = Field(ge=0)
    max_entry_chars: int = Field(ge=0)


class ModelCapabilities(StrictModel):
    languages: list[str]
    diarization: bool
    decoder_hotwords: bool
    hotwords: HotwordModelCapabilities = Field(
        default_factory=lambda: HotwordModelCapabilities(
            supported=False,
            mode="none",
            max_entries=0,
            max_entry_chars=0,
        )
    )


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
    hotword_request_version: Literal["1"] = "1"
    speaker_embedding_version: Literal["1"] = "1"
    speaker_sample_analysis_version: Literal["1"] = "1"
    upload_chunk_bytes: int = Field(gt=0)
    max_upload_bytes: int = Field(gt=0)
    max_audio_seconds: int = Field(gt=0)
    audio_formats: list[Literal["ogg"]]
    speaker_embedding_max_bytes: int = Field(gt=0)
    speaker_embedding_min_seconds: int = Field(gt=0)
    speaker_embedding_max_seconds: int = Field(gt=0)
    speaker_sample_analysis_max_files: int = Field(gt=0)
    speaker_sample_analysis_min_clip_seconds: int = Field(gt=0)
    speaker_sample_analysis_max_clip_seconds: int = Field(gt=0)
    speaker_sample_analysis_max_total_seconds: int = Field(gt=0)
    speaker_sample_analysis_min_accepted_seconds: int = Field(gt=0)
    speaker_sample_analysis_min_purity: float = Field(gt=0, le=1)


class SpeakerEmbeddingResponse(StrictModel):
    schema_version: Literal["1"] = "1"
    embedding_model: Literal["cam++"] = "cam++"
    embedding_fingerprint: str
    dimension: int = Field(gt=0)
    audio_duration: float = Field(gt=0)
    embedding: list[float] = Field(min_length=1)


class CleanSpeakerSampleRange(StrictModel):
    file_index: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class SpeakerSampleAnalysisResponse(StrictModel):
    schema_version: Literal["1"] = "1"
    outcome: Literal["enrollable", "preview_only"]
    embedding_model: Literal["cam++"] = "cam++"
    embedding_fingerprint: str
    dimension: int = Field(ge=0)
    audio_duration: float = Field(gt=0)
    accepted_audio_duration: float = Field(ge=0)
    purity_score: float = Field(ge=0, le=1)
    preview: CleanSpeakerSampleRange
    accepted_ranges: list[CleanSpeakerSampleRange]
    embedding: list[float] | None


class CreateTranscriptionJob(StrictModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_type: Literal["audio/ogg", "application/ogg"] = "audio/ogg"
    size_bytes: int = Field(gt=0)
    model: str | None = None
    language: str = Field(default="auto", min_length=1, max_length=32)
    response_format: Literal["verbose_json"] = "verbose_json"
    diarization: bool = True
    speaker_count: int | None = Field(default=None, ge=1, le=64)
    hotwords: list[str] = Field(default_factory=list)


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
