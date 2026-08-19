from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np


SPEAKER_EMBEDDING_MODEL = "iic/speech_campplus_sv_zh-cn_16k-common"
SPEAKER_EMBEDDING_FINGERPRINT = (
    "cam++:iic/speech_campplus_sv_zh-cn_16k-common:v1"
)
SPEAKER_SAMPLE_ANALYSIS_MAX_FILES = 8
SPEAKER_SAMPLE_ANALYSIS_MIN_CLIP_SECONDS = 3
SPEAKER_SAMPLE_ANALYSIS_MAX_CLIP_SECONDS = 12
SPEAKER_SAMPLE_ANALYSIS_MAX_TOTAL_SECONDS = 30
SPEAKER_SAMPLE_CHUNK_SECONDS = 1.5
SPEAKER_SAMPLE_CHUNK_SHIFT_SECONDS = 0.75
SPEAKER_SAMPLE_BOUNDARY_MARGIN_SECONDS = 0.5
SPEAKER_SAMPLE_EDGE_MARGIN_SECONDS = 0.25
SPEAKER_SAMPLE_MIN_CLEAN_RANGE_SECONDS = 3.0
SPEAKER_SAMPLE_MIN_ACCEPTED_SECONDS = 5.0
SPEAKER_SAMPLE_MIN_PURITY = 0.70
SPEAKER_SAMPLE_MAX_PREVIEW_SECONDS = 8.0
SPEAKER_SAMPLE_CANDIDATE_SIMILARITY = 0.70
SPEAKER_SAMPLE_WINDOW_SIMILARITY = 0.65


class NoCleanSpeakerSampleError(ValueError):
    """Raised only when no analyzable candidate can produce a preview."""


@dataclass(frozen=True)
class CleanSpeakerRange:
    file_index: int
    start: float
    end: float


@dataclass(frozen=True)
class SpeakerSampleAnalysis:
    outcome: str
    embedding: tuple[float, ...] | None
    audio_duration: float
    accepted_audio_duration: float
    purity_score: float
    ranges: tuple[CleanSpeakerRange, ...]
    preview: CleanSpeakerRange


@dataclass(frozen=True)
class _Window:
    file_index: int
    start: float
    end: float


@dataclass
class _Turn:
    file_index: int
    start: float
    end: float
    label: int


class SpeakerEmbeddingBackend:
    """Lazy CAM++ wrapper with a stable, normalized output contract."""

    def __init__(
        self,
        device: str,
        model_reference: tuple[str, str | None] | None = None,
    ) -> None:
        self.device = device
        self.model_reference = model_reference or (SPEAKER_EMBEDDING_MODEL, "v2.0.2")
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

            model, revision = self.model_reference
            config = {
                "model": model,
                "device": self.device,
                "disable_update": True,
                "disable_pbar": True,
            }
            if revision:
                config["model_revision"] = revision
            self._model = AutoModel(**config)

    def extract(self, audio_path: str) -> tuple[float, ...]:
        self.load()
        with self._inference_lock:
            raw_results = self._model.generate(input=audio_path, batch_size=1)
        return self._normalize_result(raw_results)

    def analyze(self, audio_paths: list[str]) -> SpeakerSampleAnalysis:
        self.load()
        if not audio_paths:
            raise NoCleanSpeakerSampleError("No candidate voice samples were supplied")

        import soundfile as sf

        clips: list[np.ndarray] = []
        durations: list[float] = []
        windows: list[_Window] = []
        chunk_audio: list[np.ndarray] = []
        chunk_samples = int(SPEAKER_SAMPLE_CHUNK_SECONDS * 16_000)
        chunk_shift = int(SPEAKER_SAMPLE_CHUNK_SHIFT_SECONDS * 16_000)
        for file_index, path in enumerate(audio_paths):
            audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
            samples = np.asarray(audio, dtype=np.float32)
            if sample_rate != 16_000 or samples.ndim != 1 or samples.size == 0:
                raise ValueError("Speaker sample analysis requires 16 kHz mono audio")
            clips.append(samples)
            durations.append(float(samples.size / sample_rate))
            last_chunk_end = 0
            for nominal_start in range(0, samples.size, chunk_shift):
                chunk_end = min(nominal_start + chunk_samples, samples.size)
                if chunk_end <= last_chunk_end:
                    break
                last_chunk_end = chunk_end
                chunk_start = max(0, chunk_end - chunk_samples)
                chunk = samples[chunk_start:chunk_end]
                if chunk.size < chunk_samples:
                    chunk = np.pad(chunk, (0, chunk_samples - chunk.size))
                windows.append(
                    _Window(
                        file_index=file_index,
                        start=chunk_start / sample_rate,
                        end=chunk_end / sample_rate,
                    )
                )
                chunk_audio.append(chunk.astype(np.float32, copy=False))

        with self._inference_lock:
            # CAM++ returns one result dictionary per inference batch, with the
            # batch dimension inside spk_embedding. A batch size of one keeps
            # every result aligned with its source clip or window.
            clip_results = self._model.generate(input=clips, batch_size=1)
            window_results = self._model.generate(input=chunk_audio, batch_size=1)
        if len(clip_results) != len(clips):
            raise ValueError("CAM++ returned incomplete candidate embeddings")
        if len(window_results) != len(windows):
            raise ValueError("CAM++ returned an incomplete sample analysis")
        clip_embeddings = np.stack(
            [self._normalize_result([result]) for result in clip_results]
        ).astype(np.float32, copy=False)
        window_embeddings = np.stack(
            [self._normalize_result([result]) for result in window_results]
        ).astype(np.float32, copy=False)

        candidate_labels = self._cluster_candidates(clip_embeddings)
        duration_by_label: dict[int, float] = {}
        count_by_label: dict[int, int] = {}
        for label_value, duration in zip(candidate_labels, durations):
            label = int(label_value)
            duration_by_label[label] = duration_by_label.get(label, 0.0) + duration
            count_by_label[label] = count_by_label.get(label, 0) + 1
        dominant_label = max(
            duration_by_label,
            key=lambda label: (duration_by_label[label], count_by_label[label], -label),
        )
        selected_files = {
            index
            for index, label in enumerate(candidate_labels)
            if int(label) == dominant_label
        }

        window_matches = np.asarray(
            [
                int(
                    window.file_index in selected_files
                    and float(embedding @ clip_embeddings[window.file_index])
                    >= SPEAKER_SAMPLE_WINDOW_SIMILARITY
                )
                for window, embedding in zip(windows, window_embeddings)
            ],
            dtype=int,
        )
        turns = self._speaker_turns(windows, window_matches, durations)
        analyzable_duration = 0.0
        stable_duration = 0.0
        stable_ranges: list[CleanSpeakerRange] = []
        preview_ranges: list[CleanSpeakerRange] = []
        for file_index in sorted(selected_files):
            clip_turns = [turn for turn in turns if turn.file_index == file_index]
            for turn_index, turn in enumerate(clip_turns):
                start_margin = (
                    SPEAKER_SAMPLE_BOUNDARY_MARGIN_SECONDS
                    if turn_index > 0
                    else SPEAKER_SAMPLE_EDGE_MARGIN_SECONDS
                )
                end_margin = (
                    SPEAKER_SAMPLE_BOUNDARY_MARGIN_SECONDS
                    if turn_index + 1 < len(clip_turns)
                    else SPEAKER_SAMPLE_EDGE_MARGIN_SECONDS
                )
                clean_start = min(turn.end, turn.start + start_margin)
                clean_end = max(clean_start, turn.end - end_margin)
                clean_duration = clean_end - clean_start
                analyzable_duration += clean_duration
                if turn.label != 1 or clean_duration <= 0:
                    continue
                stable_duration += clean_duration
                clean_range = CleanSpeakerRange(file_index, clean_start, clean_end)
                preview_ranges.append(clean_range)
                if clean_duration >= SPEAKER_SAMPLE_MIN_CLEAN_RANGE_SECONDS:
                    stable_ranges.append(clean_range)

        purity_score = stable_duration / max(analyzable_duration, 1e-12)
        accepted = tuple(stable_ranges)
        accepted_duration = sum(item.end - item.start for item in accepted)
        enrollable = (
            purity_score >= SPEAKER_SAMPLE_MIN_PURITY
            and accepted_duration >= SPEAKER_SAMPLE_MIN_ACCEPTED_SECONDS
            and bool(accepted)
        )

        if preview_ranges:
            preview_source = max(preview_ranges, key=lambda item: item.end - item.start)
        else:
            fallback_file = max(selected_files, key=lambda index: durations[index])
            fallback_start = min(SPEAKER_SAMPLE_EDGE_MARGIN_SECONDS, durations[fallback_file])
            fallback_end = max(
                fallback_start,
                durations[fallback_file] - SPEAKER_SAMPLE_EDGE_MARGIN_SECONDS,
            )
            preview_source = CleanSpeakerRange(
                fallback_file,
                fallback_start,
                fallback_end,
            )
        preview = CleanSpeakerRange(
            file_index=preview_source.file_index,
            start=preview_source.start,
            end=min(
                preview_source.end,
                preview_source.start + SPEAKER_SAMPLE_MAX_PREVIEW_SECONDS,
            ),
        )

        if not enrollable:
            return SpeakerSampleAnalysis(
                outcome="preview_only",
                embedding=None,
                audio_duration=sum(durations),
                accepted_audio_duration=accepted_duration,
                purity_score=purity_score,
                ranges=(),
                preview=preview,
            )

        clean_audio = [
            clips[item.file_index][
                round(item.start * 16_000) : round(item.end * 16_000)
            ]
            for item in accepted
        ]
        with self._inference_lock:
            clean_results = self._model.generate(input=clean_audio, batch_size=1)
        if len(clean_results) != len(accepted):
            raise ValueError("CAM++ returned an incomplete clean-sample embedding")
        clean_embeddings = np.stack(
            [self._normalize_result([result]) for result in clean_results]
        ).astype(np.float32, copy=False)
        clean_durations = np.asarray(
            [item.end - item.start for item in accepted], dtype=np.float32
        )
        embedding = np.average(clean_embeddings, axis=0, weights=clean_durations)
        norm = float(np.linalg.norm(embedding))
        if not np.isfinite(norm) or norm <= 1e-12:
            raise ValueError("CAM++ returned a zero speaker embedding")
        embedding = embedding / norm
        return SpeakerSampleAnalysis(
            outcome="enrollable",
            embedding=tuple(float(item) for item in embedding.tolist()),
            audio_duration=sum(durations),
            accepted_audio_duration=accepted_duration,
            purity_score=purity_score,
            ranges=accepted,
            preview=preview,
        )

    @staticmethod
    def _cluster_candidates(embeddings: np.ndarray) -> np.ndarray:
        sample_count = len(embeddings)
        if sample_count == 1:
            return np.zeros(1, dtype=int)
        from sklearn.cluster import AgglomerativeClustering

        cosine_distances = np.clip(1.0 - embeddings @ embeddings.T, 0.0, 2.0)
        np.fill_diagonal(cosine_distances, 0.0)
        cluster = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=1.0 - SPEAKER_SAMPLE_CANDIDATE_SIMILARITY,
            metric="precomputed",
            linkage="average",
        )
        return cluster.fit_predict(cosine_distances).astype(int, copy=False)

    @classmethod
    def _speaker_turns(
        cls,
        windows: list[_Window],
        labels: np.ndarray,
        durations: list[float],
    ) -> list[_Turn]:
        turns: list[_Turn] = []
        for file_index, duration in enumerate(durations):
            indexed = [
                (window, int(label))
                for window, label in zip(windows, labels)
                if window.file_index == file_index
            ]
            if not indexed:
                continue
            start = 0.0
            current_label = indexed[0][1]
            previous = indexed[0][0]
            clip_turns: list[_Turn] = []
            for window, label in indexed[1:]:
                if label != current_label:
                    boundary = (previous.end + window.start) / 2
                    clip_turns.append(_Turn(file_index, start, boundary, current_label))
                    start = boundary
                    current_label = label
                previous = window
            clip_turns.append(_Turn(file_index, start, duration, current_label))
            cls._smooth_short_turns(clip_turns)
            turns.extend(cls._merge_turns(clip_turns))
        return turns

    @staticmethod
    def _smooth_short_turns(turns: list[_Turn], minimum_duration: float = 0.7) -> None:
        if len(turns) < 2:
            return
        for index, turn in enumerate(turns):
            if turn.end - turn.start >= minimum_duration:
                continue
            if index == 0:
                turn.label = turns[index + 1].label
            elif index + 1 == len(turns):
                turn.label = turns[index - 1].label
            else:
                turn.label = turns[index - 1].label

    @staticmethod
    def _merge_turns(turns: list[_Turn]) -> list[_Turn]:
        merged: list[_Turn] = []
        for turn in turns:
            if merged and merged[-1].label == turn.label:
                merged[-1].end = turn.end
            else:
                merged.append(_Turn(turn.file_index, turn.start, turn.end, turn.label))
        return merged

    @staticmethod
    def _normalize_result(raw_results: Any) -> tuple[float, ...]:
        if not isinstance(raw_results, list) or not raw_results:
            raise ValueError("CAM++ returned no speaker embedding")
        raw = raw_results[0]
        if not isinstance(raw, Mapping) or raw.get("spk_embedding") is None:
            raise ValueError("CAM++ returned an invalid speaker embedding")

        value = raw["spk_embedding"]
        if hasattr(value, "detach"):
            value = value.detach().cpu().numpy()
        vector = np.asarray(value, dtype=np.float32).squeeze()
        if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
            raise ValueError("CAM++ returned an invalid speaker embedding")
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 1e-12:
            raise ValueError("CAM++ returned a zero speaker embedding")
        normalized = vector / norm
        return tuple(float(item) for item in normalized.tolist())
