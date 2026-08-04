from __future__ import annotations

import io
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from nota_asr_server.backends.base import (
    AlignedToken,
    BackendResult,
    BackendSegment,
    SpeakerTraceChunk,
)
from nota_asr_server.backends.normalization import clean_text
from nota_asr_server.backends.speaker_clustering import ClusterCapture


CAMPLUS_CHUNK_SECONDS = 1.5
CAMPLUS_SHIFT_SECONDS = 0.75
MIN_SPEAKER_TURN_SECONDS = 0.7
SPEAKER_REASSIGNMENT_MARGIN = 0.05


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: int


def capture_speaker_trace(
    raw_results: Any,
    capture: ClusterCapture | None,
) -> tuple[tuple[SpeakerTraceChunk, ...], tuple[tuple[float, ...], ...]]:
    if capture is None or capture.embeddings.ndim != 2:
        return (), ()
    intervals = _camplus_chunk_intervals(raw_results)
    if (
        not intervals
        or len(intervals) != len(capture.labels)
        or len(intervals) != capture.embeddings.shape[0]
    ):
        return (), ()

    labels = _correct_labels(capture.labels)
    speaker_count = int(labels.max()) + 1 if labels.size else 0
    centers = tuple(
        tuple(
            float(value)
            for value in np.nan_to_num(
                capture.embeddings[labels == speaker].mean(axis=0),
                copy=False,
            ).tolist()
        )
        for speaker in range(speaker_count)
    )
    trace = tuple(
        SpeakerTraceChunk(
            start=round(start, 4),
            end=round(end, 4),
            local_speaker=int(label),
            embedding=tuple(float(value) for value in embedding.tolist()),
        )
        for (start, end), label, embedding in zip(
            intervals,
            labels,
            capture.embeddings,
            strict=True,
        )
    )
    return trace, centers


def extract_aligned_tokens(raw_results: Any) -> tuple[AlignedToken, ...]:
    raw = _first_result(raw_results)
    if raw is None:
        return ()

    nano_timestamps = raw.get("timestamps")
    if isinstance(nano_timestamps, Sequence) and not isinstance(
        nano_timestamps, (str, bytes)
    ):
        tokens: list[AlignedToken] = []
        for item in nano_timestamps:
            if not isinstance(item, Mapping):
                continue
            token = str(item.get("token", ""))
            try:
                start = float(item["start_time"])
                end = float(item["end_time"])
            except (KeyError, TypeError, ValueError):
                continue
            if end < start:
                continue
            tokens.append(
                AlignedToken(
                    start=round(max(start, 0.0), 4),
                    end=round(max(end, start), 4),
                    text=token,
                )
            )
        if tokens:
            return tuple(tokens)

    words = raw.get("words")
    timestamps = raw.get("timestamp")
    if (
        not isinstance(words, Sequence)
        or isinstance(words, (str, bytes))
        or not isinstance(timestamps, Sequence)
        or isinstance(timestamps, (str, bytes))
        or len(words) != len(timestamps)
    ):
        return ()

    tokens = []
    for word, timestamp in zip(words, timestamps, strict=True):
        if (
            not isinstance(timestamp, Sequence)
            or isinstance(timestamp, (str, bytes))
            or len(timestamp) < 2
        ):
            return ()
        try:
            start = float(timestamp[0]) / 1000.0
            end = float(timestamp[1]) / 1000.0
        except (TypeError, ValueError):
            return ()
        if end < start:
            return ()
        tokens.append(
            AlignedToken(
                start=round(max(start, 0.0), 4),
                end=round(max(end, start), 4),
                text=str(word),
            )
        )
    return tuple(tokens)


def relabel_result_for_trace(raw_results: Any, result: BackendResult) -> BackendResult:
    raw = _first_result(raw_results)
    if raw is None:
        return result
    raw_segments = raw.get("sentence_info")
    if not isinstance(raw_segments, Sequence) or isinstance(raw_segments, (str, bytes)):
        return result

    raw_to_normalized: dict[str, int] = {}
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, Mapping):
            continue
        if not clean_text(raw_segment.get("text") or raw_segment.get("sentence")):
            continue
        raw_speaker = raw_segment.get("spk")
        if raw_speaker is None:
            continue
        raw_to_normalized.setdefault(str(raw_speaker), len(raw_to_normalized))

    normalized_to_raw: dict[int, int] = {}
    for raw_speaker, normalized_speaker in raw_to_normalized.items():
        try:
            normalized_to_raw[normalized_speaker] = int(raw_speaker)
        except ValueError:
            return result

    if not normalized_to_raw:
        return result
    relabeled: list[BackendSegment] = []
    for segment in result.segments:
        if segment.speaker is None:
            relabeled.append(segment)
            continue
        try:
            normalized = int(segment.speaker.removeprefix("speaker_"))
            raw_speaker = normalized_to_raw[normalized]
        except (KeyError, ValueError):
            return result
        relabeled.append(replace(segment, speaker=f"speaker_{raw_speaker}"))
    return replace(result, segments=tuple(relabeled))


def encode_speaker_trace(trace: tuple[SpeakerTraceChunk, ...]) -> bytes:
    if not trace:
        return b""
    dimensions = {len(chunk.embedding) for chunk in trace}
    if len(dimensions) != 1:
        raise ValueError("Speaker trace embeddings have inconsistent dimensions")
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer,
        starts=np.asarray([chunk.start for chunk in trace], dtype=np.float32),
        ends=np.asarray([chunk.end for chunk in trace], dtype=np.float32),
        speakers=np.asarray([chunk.local_speaker for chunk in trace], dtype=np.int16),
        embeddings=np.asarray([chunk.embedding for chunk in trace], dtype=np.float16),
    )
    return buffer.getvalue()


def decode_speaker_trace(payload: bytes | None) -> tuple[SpeakerTraceChunk, ...]:
    if not payload:
        return ()
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        starts = np.asarray(archive["starts"], dtype=np.float32)
        ends = np.asarray(archive["ends"], dtype=np.float32)
        speakers = np.asarray(archive["speakers"], dtype=np.int16)
        embeddings = np.asarray(archive["embeddings"], dtype=np.float32)
    if (
        starts.ndim != 1
        or ends.shape != starts.shape
        or speakers.shape != starts.shape
        or embeddings.ndim != 2
        or embeddings.shape[0] != len(starts)
    ):
        raise ValueError("Persisted speaker trace has an invalid shape")
    return tuple(
        SpeakerTraceChunk(
            start=float(start),
            end=float(end),
            local_speaker=int(speaker),
            embedding=tuple(float(value) for value in embedding.tolist()),
        )
        for start, end, speaker, embedding in zip(
            starts,
            ends,
            speakers,
            embeddings,
            strict=True,
        )
    )


def global_speaker_prototypes(
    traces: Sequence[tuple[int, tuple[SpeakerTraceChunk, ...]]],
    local_to_cluster: Mapping[tuple[int, int], int],
) -> dict[int, tuple[float, ...]]:
    grouped: defaultdict[int, list[np.ndarray]] = defaultdict(list)
    for window_index, trace in traces:
        for chunk in trace:
            cluster = local_to_cluster.get((window_index, chunk.local_speaker))
            if cluster is not None:
                grouped[cluster].append(np.asarray(chunk.embedding, dtype=np.float32))
    return {
        cluster: tuple(float(value) for value in np.mean(vectors, axis=0).tolist())
        for cluster, vectors in grouped.items()
        if vectors
    }


def build_speaker_turns(
    trace: tuple[SpeakerTraceChunk, ...],
    *,
    window_index: int,
    local_to_cluster: Mapping[tuple[int, int], int],
    prototypes: Mapping[int, tuple[float, ...]],
) -> tuple[SpeakerTurn, ...]:
    if not trace:
        return ()
    normalized_prototypes = {
        speaker: _normalize(np.asarray(center, dtype=np.float32))
        for speaker, center in prototypes.items()
    }
    labeled: list[SpeakerTurn] = []
    for chunk in sorted(trace, key=lambda value: (value.start, value.end)):
        initial = local_to_cluster.get((window_index, chunk.local_speaker))
        if initial is None:
            continue
        speaker = initial
        vector = _normalize(np.asarray(chunk.embedding, dtype=np.float32))
        if normalized_prototypes and np.any(vector):
            scores = {
                candidate: float(vector @ prototype)
                for candidate, prototype in normalized_prototypes.items()
            }
            best = max(scores, key=scores.__getitem__)
            initial_score = scores.get(initial, -1.0)
            if best != initial and scores[best] - initial_score >= SPEAKER_REASSIGNMENT_MARGIN:
                speaker = best
        labeled.append(SpeakerTurn(chunk.start, chunk.end, speaker))
    return _smooth_turns(labeled)


def refine_segments_with_turns(
    segments: tuple[BackendSegment, ...],
    tokens: tuple[AlignedToken, ...],
    turns: tuple[SpeakerTurn, ...],
    *,
    window_index: int,
    local_to_cluster: Mapping[tuple[int, int], int],
) -> tuple[tuple[float, float, str, int | None], ...]:
    refined: list[tuple[float, float, str, int | None]] = []
    for segment in segments:
        fallback = _fallback_cluster(segment, window_index, local_to_cluster)
        segment_tokens = tuple(
            token
            for token in tokens
            if segment.start - 0.001
            <= (token.start + token.end) / 2
            <= segment.end + 0.001
            and _compact(token.text)
        )
        split = _split_segment(segment, segment_tokens, turns, fallback)
        if split is None:
            refined.append((segment.start, segment.end, segment.text, fallback))
        else:
            refined.extend(split)
    return tuple(refined)


def _split_segment(
    segment: BackendSegment,
    tokens: tuple[AlignedToken, ...],
    turns: tuple[SpeakerTurn, ...],
    fallback: int | None,
) -> tuple[tuple[float, float, str, int | None], ...] | None:
    if not tokens or not turns:
        return None
    token_surface = "".join(_compact(token.text) for token in tokens)
    if not token_surface or token_surface != _compact(segment.text):
        return None

    speakers = tuple(_speaker_for_token(token, turns, fallback) for token in tokens)
    if any(speaker is None for speaker in speakers):
        return None
    groups: list[tuple[int, int, int]] = []
    for index, speaker in enumerate(speakers):
        assert speaker is not None
        if groups and groups[-1][2] == speaker:
            groups[-1] = (groups[-1][0], index + 1, speaker)
        else:
            groups.append((index, index + 1, speaker))
    if len(groups) == 1:
        return ((segment.start, segment.end, segment.text, groups[0][2]),)

    cumulative = []
    count = 0
    for token in tokens:
        count += len(_compact(token.text))
        cumulative.append(count)

    output: list[tuple[float, float, str, int | None]] = []
    surface_start = 0
    for group_index, (token_start, token_end, speaker) in enumerate(groups):
        surface_end = (
            len(segment.text)
            if group_index + 1 == len(groups)
            else _surface_index_for_count(segment.text, cumulative[token_end - 1])
        )
        text = segment.text[surface_start:surface_end]
        surface_start = surface_end
        if not text.strip():
            continue
        output.append(
            (
                max(segment.start, tokens[token_start].start),
                min(segment.end, max(tokens[token_end - 1].end, tokens[token_start].start)),
                text,
                speaker,
            )
        )
    return tuple(output) if output else None


def _speaker_for_token(
    token: AlignedToken,
    turns: tuple[SpeakerTurn, ...],
    fallback: int | None,
) -> int | None:
    best_speaker = fallback
    best_overlap = 0.0
    midpoint = (token.start + token.end) / 2
    for turn in turns:
        overlap = max(min(token.end, turn.end) - max(token.start, turn.start), 0.0)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker
        elif overlap == 0.0 and turn.start <= midpoint <= turn.end:
            best_speaker = turn.speaker
    return best_speaker


def _smooth_turns(turns: Sequence[SpeakerTurn]) -> tuple[SpeakerTurn, ...]:
    if not turns:
        return ()
    merged = _merge_turns(turns)
    adjusted = list(merged)
    for index, turn in enumerate(merged):
        if turn.end - turn.start >= MIN_SPEAKER_TURN_SECONDS or len(merged) == 1:
            continue
        if index == 0:
            speaker = merged[index + 1].speaker
        elif index == len(merged) - 1:
            speaker = merged[index - 1].speaker
        else:
            previous_gap = max(turn.start - merged[index - 1].end, 0.0)
            next_gap = max(merged[index + 1].start - turn.end, 0.0)
            speaker = (
                merged[index - 1].speaker
                if previous_gap <= next_gap
                else merged[index + 1].speaker
            )
        adjusted[index] = SpeakerTurn(turn.start, turn.end, speaker)
    return tuple(_merge_turns(adjusted))


def _merge_turns(turns: Sequence[SpeakerTurn]) -> list[SpeakerTurn]:
    merged: list[SpeakerTurn] = []
    for turn in sorted(turns, key=lambda value: (value.start, value.end)):
        current = turn
        if merged and merged[-1].speaker != current.speaker and merged[-1].end > current.start:
            boundary = (merged[-1].end + current.start) / 2
            merged[-1] = SpeakerTurn(merged[-1].start, boundary, merged[-1].speaker)
            current = SpeakerTurn(boundary, current.end, current.speaker)
        if (
            merged
            and merged[-1].speaker == current.speaker
            and current.start <= merged[-1].end + 1e-4
        ):
            merged[-1] = SpeakerTurn(
                merged[-1].start,
                max(merged[-1].end, current.end),
                current.speaker,
            )
        else:
            merged.append(current)
    return merged


def _fallback_cluster(
    segment: BackendSegment,
    window_index: int,
    local_to_cluster: Mapping[tuple[int, int], int],
) -> int | None:
    if segment.speaker is None:
        return None
    try:
        local_speaker = int(segment.speaker.removeprefix("speaker_"))
    except ValueError:
        return None
    return local_to_cluster.get((window_index, local_speaker))


def _camplus_chunk_intervals(raw_results: Any) -> list[tuple[float, float]]:
    raw = _first_result(raw_results)
    if raw is None:
        return []
    raw_segments = raw.get("sentence_info")
    if not isinstance(raw_segments, Sequence) or isinstance(raw_segments, (str, bytes)):
        return []
    vad_intervals: list[tuple[int, int]] = []
    for item in raw_segments:
        if not isinstance(item, Mapping):
            continue
        try:
            start_ms = int(float(item["start"]))
            end_ms = int(float(item["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        if end_ms > start_ms:
            vad_intervals.append((start_ms, end_ms))

    chunk_samples = round(CAMPLUS_CHUNK_SECONDS * 16_000)
    shift_samples = round(CAMPLUS_SHIFT_SECONDS * 16_000)
    intervals: list[tuple[float, float]] = []
    for start_ms, end_ms in sorted(vad_intervals):
        sample_count = max(end_ms * 16 - start_ms * 16, 0)
        last_chunk_end = 0
        for candidate_start in range(0, sample_count, shift_samples):
            chunk_end = min(candidate_start + chunk_samples, sample_count)
            if chunk_end <= last_chunk_end:
                break
            last_chunk_end = chunk_end
            chunk_start = max(0, chunk_end - chunk_samples)
            intervals.append(
                (
                    start_ms / 1000.0 + chunk_start / 16_000.0,
                    start_ms / 1000.0 + chunk_end / 16_000.0,
                )
            )
    return intervals


def _correct_labels(labels: np.ndarray) -> np.ndarray:
    mapping: dict[int, int] = {}
    corrected: list[int] = []
    for value in np.asarray(labels, dtype=int).tolist():
        mapping.setdefault(value, len(mapping))
        corrected.append(mapping[value])
    return np.asarray(corrected, dtype=int)


def _normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.nan_to_num(vector, copy=False)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else np.zeros_like(vector)


def _compact(value: str) -> str:
    return "".join(
        character
        for character in clean_text(value).replace("\u2581", " ")
        if not character.isspace()
    )


def _surface_index_for_count(surface: str, expected_count: int) -> int:
    count = 0
    for index, character in enumerate(surface):
        if character.isspace():
            continue
        count += 1
        if count >= expected_count:
            return index + 1
    return len(surface)


def _first_result(raw_results: Any) -> Mapping[str, Any] | None:
    if (
        isinstance(raw_results, Sequence)
        and not isinstance(raw_results, (str, bytes))
        and raw_results
        and isinstance(raw_results[0], Mapping)
    ):
        return raw_results[0]
    return None
