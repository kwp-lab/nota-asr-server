import logging

import pytest
import torch

from nota_asr_server.backends.fun_asr_nano import FunAsrNanoBackend
from nota_asr_server.backends.paraformer import ParaformerBackend
from nota_asr_server.backends.sensevoice import SenseVoiceBackend
from nota_asr_server.backends.speaker_clustering import ShortRecordingClusterBackend


class CapturingModel:
    def __init__(self) -> None:
        self.generate_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return [
            {
                "text": "<|zh|><|NEUTRAL|><|Speech|>会议开始。",
                "sentence_info": [
                    {
                        "start": 0,
                        "end": 1000,
                        "sentence": "<|zh|>会议开始。",
                        "spk": 0,
                    }
                ],
            }
        ]


class LoggingHotwordModel(CapturingModel):
    def generate(self, **kwargs):
        logging.info("Harmless FunASR inference message")
        logging.info("Hotword list: %s", [kwargs.get("hotword")])
        return super().generate(**kwargs)


def test_sensevoice_enables_native_punctuation_and_itn():
    backend = SenseVoiceBackend(device="cpu")
    model = CapturingModel()
    backend._model = model

    result = backend.transcribe(
        "/tmp/meeting.wav",
        language="auto",
        diarization=True,
        speaker_count=None,
        duration=1.0,
    )

    assert model.generate_kwargs["use_itn"] is True
    assert model.generate_kwargs["language"] == "auto"
    assert result.text == "会议开始。"
    assert result.segments[0].text == "会议开始。"
    assert result.segments[0].speaker == "speaker_0"


def test_model_specific_speaker_segmentation_modes():
    sensevoice = SenseVoiceBackend(device="cpu")
    paraformer = ParaformerBackend(device="cpu")
    nano = FunAsrNanoBackend(device="cpu")

    assert sensevoice.model_config["spk_mode"] == "vad_segment"
    assert "punc_model" not in sensevoice.model_config
    assert paraformer.model_config["punc_model"] == (
        "iic/punc_ct-transformer_cn-en-common-vocab471067-large"
    )
    assert paraformer.model_config["punc_model_revision"] == "v2.0.4"
    assert paraformer.model_config["spk_mode"] == "punc_segment"
    assert nano.model_config["spk_mode"] == "vad_segment"
    assert "punc_model" not in nano.model_config


def test_window_speaker_centers_follow_normalized_first_appearance_order():
    centers = SenseVoiceBackend._ordered_speaker_centers(
        [
            {
                "sentence_info": [
                    {"text": "second first", "spk": 1},
                    {"text": "then zero", "spk": 0},
                ],
                "spk_embedding_center": [[1.0, 0.0], [0.0, 1.0]],
            }
        ]
    )

    assert centers == ((0.0, 1.0), (1.0, 0.0))


class TraceCapturingModel:
    def __init__(self) -> None:
        self.cb_model = ShortRecordingClusterBackend(lambda embeddings, oracle_num=None: [])

    def generate(self, **kwargs):
        self.cb_model(
            torch.tensor(
                [
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ]
            ),
            oracle_num=3,
        )
        return [
            {
                "text": "甲乙丙",
                "words": ["甲", "乙", "丙"],
                "timestamp": [[100, 800], [1100, 1800], [2100, 2800]],
                "sentence_info": [
                    {
                        "start": 0,
                        "end": 3000,
                        "sentence": "甲乙丙",
                        "spk": 0,
                    }
                ],
                "spk_embedding_center": [[1.0, 0.0, 0.0]],
            }
        ]


def test_vad_window_captures_hidden_camplus_turns_without_an_extra_model_pass():
    backend = SenseVoiceBackend(device="cpu")
    backend._model = TraceCapturingModel()

    window = backend.transcribe_window(
        "/tmp/meeting.wav",
        language="auto",
        diarization=True,
        duration=3.0,
    )

    assert len(window.speaker_centers) == 3
    assert len(window.speaker_trace) == 3
    assert len({chunk.local_speaker for chunk in window.speaker_trace}) == 3
    assert [token.text for token in window.aligned_tokens] == ["甲", "乙", "丙"]
    assert window.result.segments[0].text == "甲乙丙"


class NanoCapturingModel:
    def __init__(self) -> None:
        self.generate_calls = []

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return [
            {
                "text": "会议开始。",
                "timestamps": [
                    {"token": "会", "start_time": 0.0, "end_time": 0.2},
                    {"token": "议", "start_time": 0.2, "end_time": 0.4},
                ],
                "sentence_info": [
                    {
                        "start": 0,
                        "end": 500,
                        "sentence": "会议",
                        "spk": 1,
                    },
                    {
                        "start": 500,
                        "end": 1000,
                        "sentence": "开始。",
                        "spk": 0,
                    },
                ],
                "spk_embedding_center": [[1.0, 0.0], [0.0, 1.0]],
            }
        ]


def test_nano_uses_native_punctuation_vad_and_cam_plus_plus():
    backend = FunAsrNanoBackend(device="cpu")

    assert backend.model_config["model"] == "FunAudioLLM/Fun-ASR-Nano-2512"
    assert backend.model_config["model_revision"] == "master"
    assert backend.model_config["vad_model"] == (
        "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
    )
    assert backend.model_config["vad_model_revision"] == "v2.0.4"
    assert backend.model_config["spk_model"] == (
        "iic/speech_campplus_sv_zh-cn_16k-common"
    )
    assert backend.model_config["spk_model_revision"] == "v2.0.2"
    assert backend.model_config["vad_kwargs"] == {"max_single_segment_time": 30000}
    assert backend.model_config["spk_mode"] == "vad_segment"
    assert backend.generate_config == {"itn": True}
    assert "punc_model" not in backend.model_config
    assert "trust_remote_code" not in backend.model_config
    assert backend.capabilities.languages == ("zh", "en", "ja", "yue")
    assert backend.capabilities.diarization is True
    assert backend.capabilities.decoder_hotwords is False


@pytest.mark.parametrize(
    ("language", "model_language"),
    [
        ("zh", "中文"),
        ("en", "英文"),
        ("ja", "日文"),
        ("yue", "粤语"),
    ],
)
def test_nano_maps_explicit_language_hints(language, model_language):
    backend = FunAsrNanoBackend(device="cpu")
    model = NanoCapturingModel()
    backend._model = model

    result = backend.transcribe(
        "/tmp/meeting.wav",
        language=language,
        diarization=True,
        speaker_count=2,
        duration=1.0,
    )

    assert model.generate_calls[0]["language"] == model_language
    assert model.generate_calls[0]["itn"] is True
    assert model.generate_calls[0]["output_timestamp"] is True
    assert model.generate_calls[0]["preset_spk_num"] == 2
    assert result.language == language


def test_nano_auto_language_is_omitted_and_reported_as_und():
    backend = FunAsrNanoBackend(device="cpu")
    model = NanoCapturingModel()
    backend._model = model

    result = backend.transcribe(
        "/tmp/meeting.wav",
        language="auto",
        diarization=False,
        speaker_count=None,
        duration=1.0,
    )

    assert "language" not in model.generate_calls[0]
    assert result.language == "und"


def test_paraformer_maps_hotwords_to_decoder_bias_parameter():
    backend = ParaformerBackend(device="cpu")
    model = CapturingModel()
    backend._model = model

    backend.transcribe(
        "/tmp/meeting.wav",
        language="auto",
        diarization=False,
        speaker_count=None,
        duration=1.0,
        hotwords=("Nota", "千问"),
    )

    assert model.generate_kwargs["hotword"] == "Nota 千问"


def test_funasr_hotword_values_are_removed_from_upstream_logs(caplog):
    backend = ParaformerBackend(device="cpu")
    backend._model = LoggingHotwordModel()
    caplog.set_level(logging.INFO)

    backend.transcribe(
        "/tmp/meeting.wav",
        language="auto",
        diarization=False,
        speaker_count=None,
        duration=1.0,
        hotwords=("private-hotword-sentinel",),
    )

    assert "Harmless FunASR inference message" in caplog.text
    assert "private-hotword-sentinel" not in caplog.text
    assert "Hotword list" not in caplog.text


def test_nano_maps_hotwords_to_prompt_list():
    backend = FunAsrNanoBackend(device="cpu")
    model = NanoCapturingModel()
    backend._model = model

    backend.transcribe(
        "/tmp/meeting.wav",
        language="auto",
        diarization=False,
        speaker_count=None,
        duration=1.0,
        hotwords=("Nota", "千问"),
    )

    assert model.generate_calls[0]["hotwords"] == ["Nota", "千问"]


def test_nano_window_normalizes_segments_and_orders_speaker_centers():
    backend = FunAsrNanoBackend(device="cpu")
    model = NanoCapturingModel()
    backend._model = model

    window = backend.transcribe_window(
        "/tmp/meeting.wav",
        language="auto",
        diarization=True,
        duration=1.0,
    )

    assert [segment.text for segment in window.result.segments] == ["会议", "开始。"]
    assert [segment.speaker for segment in window.result.segments] == [
        "speaker_0",
        "speaker_1",
    ]
    assert window.speaker_centers == ((0.0, 1.0), (1.0, 0.0))
    assert model.generate_calls[0]["return_spk_center"] is True
