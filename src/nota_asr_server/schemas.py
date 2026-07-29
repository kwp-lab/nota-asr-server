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

