from __future__ import annotations

import pytest

from nota_asr_server.schemas import TranscriptionSegment
from nota_asr_server.transcripts import (
    RENDERED_RESPONSE_FORMATS,
    RESULT_RESPONSE_FORMATS,
    SUPPORTED_RESPONSE_FORMATS,
    format_timestamp,
    is_rendered_format,
    render,
)


def segment(id_, start, end, text, speaker=None):
    return TranscriptionSegment(id=id_, start=start, end=end, text=text, speaker=speaker)


SEGMENTS = [
    segment(0, 0.5, 2.5, "会议开始。", "speaker_0"),
    segment(1, 2.5, 3661.004, "第二句。", "speaker_1"),
]


def test_supported_format_sets_stay_aligned():
    assert SUPPORTED_RESPONSE_FORMATS == ("json", "verbose_json", "text", "srt", "vtt")
    assert RESULT_RESPONSE_FORMATS == ("verbose_json", "text", "srt", "vtt")
    assert all(is_rendered_format(item) for item in RENDERED_RESPONSE_FORMATS)
    assert not is_rendered_format("verbose_json")
    assert not is_rendered_format("json")


@pytest.mark.parametrize(
    ("seconds", "separator", "expected"),
    [
        (0, ",", "00:00:00,000"),
        (0.5, ",", "00:00:00,500"),
        (3661.004, ",", "01:01:01,004"),
        (3661.004, ".", "01:01:01.004"),
        (-1.0, ",", "00:00:00,000"),
    ],
)
def test_format_timestamp(seconds, separator, expected):
    assert format_timestamp(seconds, millisecond_separator=separator) == expected


def test_srt_carries_cue_times_and_speaker_labels():
    rendered = render("srt", text="会议开始。第二句。", segments=SEGMENTS)

    assert rendered.media_type == "application/x-subrip; charset=utf-8"
    assert rendered.body == (
        "1\n"
        "00:00:00,500 --> 00:00:02,500\n"
        "speaker_0: 会议开始。\n"
        "\n"
        "2\n"
        "00:00:02,500 --> 01:01:01,004\n"
        "speaker_1: 第二句。\n"
    )


def test_vtt_uses_the_webvtt_header_and_dot_separator():
    rendered = render("vtt", text="会议开始。第二句。", segments=SEGMENTS)

    assert rendered.media_type == "text/vtt; charset=utf-8"
    assert rendered.body == (
        "WEBVTT\n"
        "\n"
        "00:00:00.500 --> 00:00:02.500\n"
        "speaker_0: 会议开始。\n"
        "\n"
        "00:00:02.500 --> 01:01:01.004\n"
        "speaker_1: 第二句。\n"
    )


def test_text_stays_the_plain_transcript():
    rendered = render("text", text="会议开始。", segments=SEGMENTS)

    assert rendered.media_type == "text/plain; charset=utf-8"
    assert rendered.body == "会议开始。"


def test_missing_speaker_labels_are_omitted_without_a_separator():
    rendered = render("srt", text="匿名。", segments=[segment(0, 0.0, 1.0, "匿名。")])

    assert rendered.body == "1\n00:00:00,000 --> 00:00:01,000\n匿名。\n"


def test_blank_segments_do_not_produce_cues():
    segments = [
        segment(0, 0.0, 1.0, "   ", "speaker_0"),
        segment(1, 1.0, 2.0, "有内容。", "speaker_0"),
    ]

    rendered = render("srt", text="有内容。", segments=segments)

    assert rendered.body == "1\n00:00:01,000 --> 00:00:02,000\nspeaker_0: 有内容。\n"


def test_cue_end_never_precedes_its_start():
    rendered = render("vtt", text="乱序。", segments=[segment(0, 5.0, 4.0, "乱序。")])

    assert "00:00:05.000 --> 00:00:05.000" in rendered.body


def test_empty_transcripts_render_without_cues():
    assert render("srt", text="", segments=[]).body == ""
    assert render("vtt", text="", segments=[]).body == "WEBVTT\n"
    assert render("text", text="", segments=[]).body == ""


def test_unknown_rendered_format_is_rejected():
    with pytest.raises(ValueError):
        render("json", text="会议开始。", segments=SEGMENTS)
