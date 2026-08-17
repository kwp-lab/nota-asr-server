from __future__ import annotations

import pytest

from nota_asr_server.schemas import TranscriptionSegment
from nota_asr_server.transcripts import format_timestamp, render


def segment(start, end, text, speaker=None):
    return TranscriptionSegment(id=0, start=start, end=end, text=text, speaker=speaker)


@pytest.mark.parametrize(
    ("seconds", "separator", "expected"),
    [
        (0.5, ",", "00:00:00,500"),
        (3661.004, ",", "01:01:01,004"),
        (3661.004, ".", "01:01:01.004"),
        (-1.0, ",", "00:00:00,000"),
    ],
)
def test_format_timestamp_covers_the_hour_and_zero_boundaries(seconds, separator, expected):
    assert format_timestamp(seconds, millisecond_separator=separator) == expected


def test_blank_segments_do_not_produce_cues():
    segments = [segment(0.0, 1.0, "   ", "speaker_0"), segment(1.0, 2.0, "有内容。", "speaker_0")]

    assert render("srt", text="有内容。", segments=segments).body == (
        "1\n00:00:01,000 --> 00:00:02,000\nspeaker_0: 有内容。\n"
    )


def test_cue_end_never_precedes_its_start():
    rendered = render("vtt", text="乱序。", segments=[segment(5.0, 4.0, "乱序。")])

    assert "00:00:05.000 --> 00:00:05.000" in rendered.body


def test_empty_transcripts_render_without_cues():
    assert render("srt", text="", segments=[]).body == ""
    assert render("vtt", text="", segments=[]).body == "WEBVTT\n"
