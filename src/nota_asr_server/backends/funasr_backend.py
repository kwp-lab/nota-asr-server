from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any

from nota_asr_server.backends.base import ASRBackend, BackendCapabilities, BackendResult
from nota_asr_server.backends.normalization import normalize_funasr_result
from nota_asr_server.backends.speaker_clustering import ShortRecordingClusterBackend


class FunASRBackend(ASRBackend):
    def __init__(
        self,
        *,
        alias: str,
        device: str,
        model_config: Mapping[str, Any],
        capabilities: BackendCapabilities,
        accepts_language_hint: bool,
        generate_config: Mapping[str, Any] | None = None,
    ) -> None:
        self.alias = alias
        self.device = device
        self.model_config = dict(model_config)
        self.capabilities = capabilities
        self.accepts_language_hint = accepts_language_hint
        self.generate_config = dict(generate_config or {})
        self._model: Any = None
        self._load_lock = threading.RLock()
        self._inference_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self.loaded:
            return
        with self._load_lock:
            if self.loaded:
                return
            from funasr import AutoModel

            config = dict(self.model_config)
            config.update(
                {
                    "device": self.device,
                    "disable_update": True,
                    "disable_pbar": True,
                }
            )
            self._model = AutoModel(**config)
            if self.capabilities.diarization and self._model.cb_model is not None:
                self._model.cb_model = ShortRecordingClusterBackend(self._model.cb_model)

    def transcribe(
        self,
        audio_path: str,
        *,
        language: str,
        diarization: bool,
        speaker_count: int | None,
        duration: float,
    ) -> BackendResult:
        self.load()
        generate_kwargs = dict(self.generate_config)
        generate_kwargs.update(
            {
                "input": audio_path,
                "batch_size": 1,
                "return_spk_res": diarization,
                "output_timestamp": True,
                "return_time_stamps": True,
            }
        )
        if self.accepts_language_hint:
            generate_kwargs["language"] = language or "auto"
        if diarization and speaker_count is not None:
            generate_kwargs["preset_spk_num"] = speaker_count

        with self._inference_lock:
            started = time.perf_counter()
            raw_results = self._model.generate(**generate_kwargs)
            elapsed = time.perf_counter() - started

        return normalize_funasr_result(
            raw_results,
            requested_language=language,
            media_duration=duration,
            processing_time=elapsed,
            diarization=diarization,
        )
