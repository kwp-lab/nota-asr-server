from nota_asr_server.backends.base import BackendCapabilities
from nota_asr_server.backends.funasr_backend import FunASRBackend


class FunAsrNanoBackend(FunASRBackend):
    _LANGUAGE_HINTS = {
        "zh": "中文",
        "en": "英文",
        "ja": "日文",
        "yue": "粤语",
    }

    def __init__(self, device: str) -> None:
        super().__init__(
            alias="fun-asr-nano",
            device=device,
            model_config={
                "model": "FunAudioLLM/Fun-ASR-Nano-2512",
                "vad_model": "fsmn-vad",
                "vad_kwargs": {"max_single_segment_time": 30000},
                "spk_model": "cam++",
                "spk_mode": "vad_segment",
            },
            capabilities=BackendCapabilities(
                languages=("zh", "en", "ja", "yue"),
                diarization=True,
                decoder_hotwords=False,
            ),
            accepts_language_hint=True,
            generate_config={"itn": True},
        )

    def _model_language_hint(self, language: str) -> str | None:
        normalized = language.strip().lower()
        if not normalized or normalized == "auto":
            return None
        return self._LANGUAGE_HINTS.get(normalized, language.strip())
