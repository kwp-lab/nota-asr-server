from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class BackendCapabilities:
    languages: tuple[str, ...]
    diarization: bool = True
    decoder_hotwords: bool = False


@dataclass(frozen=True)
class BackendSegment:
    start: float
    end: float
    text: str
    speaker: str | None


@dataclass(frozen=True)
class BackendResult:
    text: str
    language: str
    duration: float
    processing_time: float
    segments: tuple[BackendSegment, ...]


class ASRBackend(ABC):
    alias: str
    capabilities: BackendCapabilities

    @property
    @abstractmethod
    def loaded(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        *,
        language: str,
        diarization: bool,
        speaker_count: int | None,
        duration: float,
    ) -> BackendResult:
        raise NotImplementedError

