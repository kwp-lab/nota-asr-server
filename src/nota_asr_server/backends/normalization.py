from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from nota_asr_server.backends.base import BackendResult, BackendSegment


_RICH_TAG_RE = re.compile(r"<\|[^|]*\|>")
_LANGUAGE_TAG_RE = re.compile(r"<\|(zh|en|yue|ja|ko)\|>")
_SUPPORTED_LANGUAGES = {"zh", "en", "yue", "ja", "ko"}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return _RICH_TAG_RE.sub("", str(value)).strip()


def _resolve_language(raw_text: str, requested: str) -> str:
    match = _LANGUAGE_TAG_RE.search(raw_text)
    if match:
        return match.group(1)
    requested = requested.strip().lower()
    if requested and requested != "auto" and requested in _SUPPORTED_LANGUAGES:
        return requested
    return "und"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_funasr_result(
    raw_results: Any,
    *,
    requested_language: str,
    media_duration: float,
    processing_time: float,
    diarization: bool,
) -> BackendResult:
    if not isinstance(raw_results, Sequence) or isinstance(raw_results, (str, bytes)):
        raise ValueError("FunASR returned an invalid result container")
    if not raw_results or not isinstance(raw_results[0], Mapping):
        raise ValueError("FunASR returned no transcription result")

    result = raw_results[0]
    raw_text = str(result.get("text", ""))
    text = clean_text(raw_text)
    language = _resolve_language(raw_text, requested_language)
    raw_segments = result.get("sentence_info")
    speaker_names: dict[str, str] = {}
    segments: list[BackendSegment] = []

    if isinstance(raw_segments, Sequence) and not isinstance(raw_segments, (str, bytes)):
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, Mapping):
                continue
            segment_text = clean_text(raw_segment.get("text") or raw_segment.get("sentence"))
            if not segment_text:
                continue
            start = max(_number(raw_segment.get("start")) / 1000.0, 0.0)
            end = max(_number(raw_segment.get("end")) / 1000.0, start)
            raw_speaker = raw_segment.get("spk") if diarization else None
            speaker = None
            if raw_speaker is not None:
                speaker_key = str(raw_speaker)
                if speaker_key not in speaker_names:
                    speaker_names[speaker_key] = f"speaker_{len(speaker_names)}"
                speaker = speaker_names[speaker_key]
            segments.append(
                BackendSegment(
                    start=round(start, 3),
                    end=round(end, 3),
                    text=segment_text,
                    speaker=speaker,
                )
            )

    effective_duration = max(float(media_duration), max((item.end for item in segments), default=0.0))
    if not segments and text:
        segments.append(
            BackendSegment(
                start=0.0,
                end=round(effective_duration, 3),
                text=text,
                speaker=None,
            )
        )

    if not text and segments:
        text = "".join(segment.text for segment in segments)

    return BackendResult(
        text=text,
        language=language,
        duration=round(effective_duration, 3),
        processing_time=round(max(processing_time, 0.0), 3),
        segments=tuple(segments),
    )

