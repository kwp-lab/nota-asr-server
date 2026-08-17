"""Rendering of public transcript response formats.

The stable JSON contract already carries per-segment ``start`` and ``end``
times. These renderers expose the same times in the plain-text subtitle
formats that OpenAI transcription clients already understand, so a client can
export a timestamped transcript without re-implementing cue formatting.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from nota_asr_server.schemas import TranscriptionSegment


JSON_RESPONSE_FORMATS = ("json", "verbose_json")
RENDERED_RESPONSE_FORMATS = ("text", "srt", "vtt")
SUPPORTED_RESPONSE_FORMATS = JSON_RESPONSE_FORMATS + RENDERED_RESPONSE_FORMATS
"""Formats accepted by ``POST /v1/audio/transcriptions``."""

RESULT_RESPONSE_FORMATS = ("verbose_json",) + RENDERED_RESPONSE_FORMATS
"""Formats accepted when reading a durable Nota batch job result."""

_MEDIA_TYPES = {
    "text": "text/plain; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
}


@dataclass(frozen=True)
class RenderedTranscript:
    """A transcript serialized as plain text plus its response media type."""

    body: str
    media_type: str


def is_rendered_format(response_format: str) -> bool:
    return response_format in RENDERED_RESPONSE_FORMATS


def format_timestamp(seconds: float, *, millisecond_separator: str) -> str:
    """Format ``seconds`` as ``HH:MM:SS<sep>mmm``.

    Cue times are clamped at zero because subtitle formats have no
    representation for a negative offset.
    """
    total_milliseconds = max(int(round(float(seconds) * 1000)), 0)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
        f"{millisecond_separator}{milliseconds:03d}"
    )


def _cue_text(segment: TranscriptionSegment) -> str:
    text = segment.text.strip()
    if segment.speaker:
        return f"{segment.speaker}: {text}"
    return text


def _cues(segments: Iterable[TranscriptionSegment]) -> list[TranscriptionSegment]:
    return [segment for segment in segments if segment.text.strip()]


def render_srt(segments: Sequence[TranscriptionSegment]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(_cues(segments), start=1):
        start = format_timestamp(segment.start, millisecond_separator=",")
        end = format_timestamp(max(segment.end, segment.start), millisecond_separator=",")
        blocks.append(f"{index}\n{start} --> {end}\n{_cue_text(segment)}\n")
    return "\n".join(blocks)


def render_vtt(segments: Sequence[TranscriptionSegment]) -> str:
    blocks: list[str] = ["WEBVTT\n"]
    for segment in _cues(segments):
        start = format_timestamp(segment.start, millisecond_separator=".")
        end = format_timestamp(max(segment.end, segment.start), millisecond_separator=".")
        blocks.append(f"{start} --> {end}\n{_cue_text(segment)}\n")
    return "\n".join(blocks)


def render(
    response_format: str,
    *,
    text: str,
    segments: Sequence[TranscriptionSegment],
) -> RenderedTranscript:
    """Render a transcript for one of ``RENDERED_RESPONSE_FORMATS``."""
    if response_format == "text":
        body = text
    elif response_format == "srt":
        body = render_srt(segments)
    elif response_format == "vtt":
        body = render_vtt(segments)
    else:
        raise ValueError(f"Unsupported rendered response format: {response_format}")
    return RenderedTranscript(body=body, media_type=_MEDIA_TYPES[response_format])
