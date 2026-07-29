from __future__ import annotations

import threading
from collections.abc import Callable

from nota_asr_server.backends import ParaformerBackend, SenseVoiceBackend
from nota_asr_server.backends.base import ASRBackend, BackendResult
from nota_asr_server.config import Settings
from nota_asr_server.errors import ModelLoadError, UnknownModelError


BackendFactory = Callable[[str], ASRBackend]


class ModelManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._factories: dict[str, BackendFactory] = {
            "sensevoice": SenseVoiceBackend,
            "paraformer": ParaformerBackend,
        }
        self._backends: dict[str, ASRBackend] = {}
        self._load_errors: dict[str, str] = {}
        self._load_lock = threading.RLock()
        self._inference_gate = threading.BoundedSemaphore(
            settings.max_concurrent_inferences
        )

    def preload(self) -> None:
        self.get_backend(self.settings.preload_model)

    def get_backend(self, name: str) -> ASRBackend:
        if name not in self.settings.enabled_models or name not in self._factories:
            raise UnknownModelError(name)

        backend = self._backends.get(name)
        if backend is not None and backend.loaded:
            return backend

        with self._load_lock:
            backend = self._backends.get(name)
            if backend is None:
                backend = self._factories[name](self.settings.device)
                self._backends[name] = backend
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
    ) -> BackendResult:
        backend = self.get_backend(model)
        with self._inference_gate:
            return backend.transcribe(
                audio_path,
                language=language,
                diarization=diarization,
                speaker_count=speaker_count,
                duration=duration,
            )

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
                backend = self._factories[name](self.settings.device)
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
                    },
                }
            )
        return items

