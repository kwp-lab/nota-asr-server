from __future__ import annotations

import os
import threading
from nota_asr_server.backends import (
    FunAsrNanoBackend,
    ParaformerBackend,
    SenseVoiceBackend,
)
from nota_asr_server.backends.base import (
    ASRBackend,
    BackendCapabilities,
    BackendResult,
    BackendWindowResult,
)
from nota_asr_server.backends.speaker_embedding import (
    SpeakerEmbeddingBackend,
    SpeakerSampleAnalysis,
)
from nota_asr_server.config import Settings
from nota_asr_server.errors import ModelLoadError, UnknownModelError
from nota_asr_server.services.model_store import ModelStore


class ModelManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.model_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MODELSCOPE_CACHE"] = str(self.settings.model_dir)
        self.model_store = ModelStore(self.settings.model_dir)
        self._backend_types: dict[str, type[ASRBackend]] = {
            "sensevoice": SenseVoiceBackend,
            "paraformer": ParaformerBackend,
            "fun-asr-nano": FunAsrNanoBackend,
        }
        self._backends: dict[str, ASRBackend] = {}
        self._load_errors: dict[str, str] = {}
        self._speaker_embedding_backend: SpeakerEmbeddingBackend | None = None
        self._load_lock = threading.RLock()
        self._inference_gate = threading.BoundedSemaphore(
            settings.max_concurrent_inferences
        )

    def preload(self) -> None:
        self.get_backend(self.settings.preload_model)

    def _component_references(
        self, model: str
    ) -> dict[str, tuple[str, str | None]]:
        definition = self.model_store.catalog.model(model)
        return {
            key: self.model_store.reference(
                key, policy=self.settings.model_download_policy
            )
            for key in definition.components
        }

    def _new_backend(self, name: str) -> ASRBackend:
        backend_type = self._backend_types[name]
        return backend_type(
            self.settings.device,
            self._component_references(name),
        )

    def get_backend(self, name: str) -> ASRBackend:
        if name not in self.settings.enabled_models or name not in self._backend_types:
            raise UnknownModelError(name)

        backend = self._backends.get(name)
        if backend is not None and backend.loaded:
            return backend

        with self._load_lock:
            backend = self._backends.get(name)
            if backend is None:
                try:
                    backend = self._new_backend(name)
                    self._backends[name] = backend
                except Exception as exc:
                    self._load_errors[name] = str(exc)
                    raise ModelLoadError(name) from exc
            if not backend.loaded:
                try:
                    backend.load()
                    self._load_errors.pop(name, None)
                except Exception as exc:
                    self._load_errors[name] = str(exc)
                    raise ModelLoadError(name) from exc
            return backend

    def transcribe(
        self,
        model: str,
        audio_path: str,
        *,
        language: str,
        diarization: bool,
        speaker_count: int | None,
        duration: float,
        hotwords: tuple[str, ...] = (),
    ) -> BackendResult:
        backend = self.get_backend(model)
        with self._inference_gate:
            return backend.transcribe(
                audio_path,
                language=language,
                diarization=diarization,
                speaker_count=speaker_count,
                duration=duration,
                hotwords=hotwords,
            )

    def transcribe_window(
        self,
        model: str,
        audio_path: str,
        *,
        language: str,
        diarization: bool,
        duration: float,
        hotwords: tuple[str, ...] = (),
    ) -> BackendWindowResult:
        backend = self.get_backend(model)
        with self._inference_gate:
            return backend.transcribe_window(
                audio_path,
                language=language,
                diarization=diarization,
                duration=duration,
                hotwords=hotwords,
            )

    def cluster_speaker_centers(
        self,
        model: str,
        centers: tuple[tuple[float, ...], ...],
        *,
        speaker_count: int | None,
    ) -> tuple[int, ...]:
        backend = self.get_backend(model)
        with self._inference_gate:
            return backend.cluster_speaker_centers(
                centers,
                speaker_count=speaker_count,
            )

    def extract_speaker_embedding(self, audio_path: str) -> tuple[float, ...]:
        with self._inference_gate:
            return self._speaker_backend().extract(audio_path)

    def analyze_speaker_samples(
        self, audio_paths: list[str]
    ) -> SpeakerSampleAnalysis:
        with self._inference_gate:
            return self._speaker_backend().analyze(audio_paths)

    def _speaker_backend(self) -> SpeakerEmbeddingBackend:
        if self._speaker_embedding_backend is None:
            reference = self.model_store.reference(
                "campplus", policy=self.settings.model_download_policy
            )
            self._speaker_embedding_backend = SpeakerEmbeddingBackend(
                self.settings.device, reference
            )
        return self._speaker_embedding_backend

    @property
    def ready(self) -> bool:
        backend = self._backends.get(self.settings.preload_model)
        return bool(backend and backend.loaded)

    @property
    def loaded_models(self) -> list[str]:
        return sorted(name for name, backend in self._backends.items() if backend.loaded)

    @property
    def readiness_detail(self) -> str | None:
        return self._load_errors.get(self.settings.preload_model)

    def list_models(self) -> list[dict[str, object]]:
        items = []
        for name in self.settings.enabled_models:
            backend = self._backends.get(name)
            if backend is None:
                backend = self._backend_types[name](self.settings.device)
            capabilities = backend.capabilities
            items.append(
                {
                    "id": name,
                    "object": "model",
                    "owned_by": "nota",
                    "ready": bool(self._backends.get(name) and self._backends[name].loaded),
                    "capabilities": {
                        "languages": list(capabilities.languages),
                        "diarization": capabilities.diarization,
                        "decoder_hotwords": capabilities.decoder_hotwords,
                        "hotwords": self._hotword_capabilities(capabilities),
                    },
                }
            )
        return items

    def model_capabilities(self, name: str) -> BackendCapabilities:
        if name not in self.settings.enabled_models or name not in self._backend_types:
            raise UnknownModelError(name)
        backend = self._backends.get(name)
        if backend is None:
            backend = self._backend_types[name](self.settings.device)
        return backend.capabilities

    @staticmethod
    def _hotword_capabilities(capabilities: BackendCapabilities) -> dict[str, object]:
        return {
            "supported": capabilities.hotword_mode != "none",
            "mode": capabilities.hotword_mode,
            "max_entries": capabilities.hotword_max_entries,
            "max_entry_chars": capabilities.hotword_max_entry_chars,
        }
