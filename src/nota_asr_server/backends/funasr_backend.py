from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any

import numpy as np

from nota_asr_server.backends.base import (
    ASRBackend,
    BackendCapabilities,
    BackendResult,
    BackendWindowResult,
)
from nota_asr_server.backends.normalization import normalize_funasr_result
from nota_asr_server.backends.speaker_clustering import (
    ShortRecordingClusterBackend,
    cluster_meeting_speaker_centers,
)
from nota_asr_server.backends.turn_alignment import (
    capture_speaker_trace,
    extract_aligned_tokens,
    relabel_result_for_trace,
)


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
        self._apply_language_hint(generate_kwargs, language)
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

    def _model_language_hint(self, language: str) -> str | None:
        return language or "auto"

    def _apply_language_hint(
        self,
        generate_kwargs: dict[str, Any],
        language: str,
    ) -> None:
        if not self.accepts_language_hint:
            return
        model_language = self._model_language_hint(language)
        if model_language is not None:
            generate_kwargs["language"] = model_language

    def transcribe_window(
        self,
        audio_path: str,
        *,
        language: str,
        diarization: bool,
        duration: float,
    ) -> BackendWindowResult:
        self.load()
        generate_kwargs = dict(self.generate_config)
        generate_kwargs.update(
            {
                "input": audio_path,
                "batch_size": 1,
                "return_spk_res": diarization,
                "return_spk_center": diarization,
                "output_timestamp": True,
                "return_time_stamps": True,
            }
        )
        self._apply_language_hint(generate_kwargs, language)

        capture_backend = (
            getattr(self._model, "cb_model", None)
            if diarization
            and self.model_config.get("spk_mode") == "vad_segment"
            and isinstance(
                getattr(self._model, "cb_model", None),
                ShortRecordingClusterBackend,
            )
            else None
        )
        capture = None
        with self._inference_lock:
            if capture_backend is not None:
                capture_backend.clear_capture()
            started = time.perf_counter()
            try:
                raw_results = self._model.generate(**generate_kwargs)
            finally:
                elapsed = time.perf_counter() - started
                if capture_backend is not None:
                    capture = capture_backend.take_capture()

        result = normalize_funasr_result(
            raw_results,
            requested_language=language,
            media_duration=duration,
            processing_time=elapsed,
            diarization=diarization,
        )
        speaker_trace = ()
        aligned_tokens = ()
        centers = self._ordered_speaker_centers(raw_results) if diarization else ()
        if diarization and capture_backend is not None:
            speaker_trace, trace_centers = capture_speaker_trace(raw_results, capture)
            if speaker_trace and trace_centers:
                centers = trace_centers
                aligned_tokens = extract_aligned_tokens(raw_results)
                result = relabel_result_for_trace(raw_results, result)
        if diarization and result.text and any(segment.speaker for segment in result.segments):
            expected = {
                int(segment.speaker.removeprefix("speaker_"))
                for segment in result.segments
                if segment.speaker
            }
            if not centers or max(expected, default=-1) >= len(centers):
                raise ValueError("FunASR did not return speaker centers for voiced segments")
        return BackendWindowResult(
            result=result,
            speaker_centers=centers,
            speaker_trace=speaker_trace,
            aligned_tokens=aligned_tokens,
        )

    def cluster_speaker_centers(
        self,
        centers: tuple[tuple[float, ...], ...],
        *,
        speaker_count: int | None,
    ) -> tuple[int, ...]:
        if not centers:
            return ()
        labels = cluster_meeting_speaker_centers(
            centers,
            speaker_count=speaker_count,
        )
        return tuple(int(value) for value in np.asarray(labels).tolist())

    @staticmethod
    def _ordered_speaker_centers(raw_results: Any) -> tuple[tuple[float, ...], ...]:
        if not isinstance(raw_results, list) or not raw_results:
            return ()
        raw = raw_results[0]
        if not isinstance(raw, Mapping):
            return ()
        raw_centers = raw.get("spk_embedding_center")
        raw_segments = raw.get("sentence_info")
        if raw_centers is None or not isinstance(raw_segments, list):
            return ()

        matrix = np.asarray(raw_centers, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] == 0:
            return ()
        raw_to_normalized: dict[str, int] = {}
        for segment in raw_segments:
            if not isinstance(segment, Mapping) or segment.get("spk") is None:
                continue
            key = str(segment["spk"])
            raw_to_normalized.setdefault(key, len(raw_to_normalized))
        if not raw_to_normalized:
            return ()

        ordered: list[tuple[float, ...] | None] = [None] * len(raw_to_normalized)
        for raw_label, normalized_label in raw_to_normalized.items():
            try:
                raw_index = int(raw_label)
            except ValueError:
                return ()
            if raw_index < 0 or raw_index >= matrix.shape[0]:
                return ()
            center = np.nan_to_num(matrix[raw_index], copy=False)
            ordered[normalized_label] = tuple(float(value) for value in center.tolist())
        if any(center is None for center in ordered):
            return ()
        return tuple(center for center in ordered if center is not None)
