from nota_asr_server.backends.normalization import normalize_funasr_result


def test_sensevoice_result_is_cleaned_and_speakers_are_stable():
    raw = [
        {
            "text": "<|zh|><|NEUTRAL|><|Speech|>大家好今天开会",
            "sentence_info": [
                {"start": 500, "end": 2100, "text": "<|zh|>大家好", "spk": 8},
                {"start": 2300, "end": 4400, "sentence": "今天开会", "spk": 3},
                {"start": 4500, "end": 5200, "text": "继续", "spk": 8},
            ],
        }
    ]

    result = normalize_funasr_result(
        raw,
        requested_language="auto",
        media_duration=6.0,
        processing_time=1.23456,
        diarization=True,
    )

    assert result.text == "大家好今天开会"
    assert result.language == "zh"
    assert result.duration == 6.0
    assert result.processing_time == 1.235
    assert [segment.speaker for segment in result.segments] == [
        "speaker_0",
        "speaker_1",
        "speaker_0",
    ]
    assert result.segments[0].start == 0.5


def test_paraformer_shape_normalizes_to_the_same_internal_contract():
    raw = [
        {
            "text": "大家好，今天开会。",
            "sentence_info": [
                {"start": 500, "end": 2100, "sentence": "大家好，", "spk": 0},
                {"start": 2300, "end": 4400, "sentence": "今天开会。", "spk": 1},
            ],
        }
    ]

    result = normalize_funasr_result(
        raw,
        requested_language="zh",
        media_duration=4.4,
        processing_time=0.8,
        diarization=True,
    )

    assert result.language == "zh"
    assert result.text == "大家好，今天开会。"
    assert result.segments[0].speaker == "speaker_0"
    assert result.segments[1].speaker == "speaker_1"
    assert set(result.segments[0].__dict__) == {"start", "end", "text", "speaker"}


def test_missing_sentence_info_gets_a_schema_safe_fallback_segment():
    result = normalize_funasr_result(
        [{"text": "single transcript"}],
        requested_language="auto",
        media_duration=3.2,
        processing_time=0.2,
        diarization=True,
    )

    assert result.language == "und"
    assert len(result.segments) == 1
    assert result.segments[0].end == 3.2
    assert result.segments[0].speaker is None


def test_diarization_false_suppresses_raw_speaker_labels():
    result = normalize_funasr_result(
        [
            {
                "text": "hello",
                "sentence_info": [
                    {"start": 0, "end": 1000, "text": "hello", "spk": 4}
                ],
            }
        ],
        requested_language="en",
        media_duration=1.0,
        processing_time=0.1,
        diarization=False,
    )

    assert result.segments[0].speaker is None

