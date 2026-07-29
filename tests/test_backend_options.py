from nota_asr_server.backends.sensevoice import SenseVoiceBackend


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
