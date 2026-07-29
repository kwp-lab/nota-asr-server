from nota_asr_server.backends.base import BackendCapabilities
from nota_asr_server.backends.funasr_backend import FunASRBackend


class SenseVoiceBackend(FunASRBackend):
    def __init__(self, device: str) -> None:
        super().__init__(
            alias="sensevoice",
            device=device,
            model_config={
                "model": "iic/SenseVoiceSmall",
                "vad_model": "fsmn-vad",
                "vad_kwargs": {"max_single_segment_time": 30000},
                "spk_model": "cam++",
                "spk_mode": "vad_segment",
            },
            capabilities=BackendCapabilities(
                languages=("zh", "en", "ja", "ko", "yue"),
                diarization=True,
                decoder_hotwords=False,
            ),
            accepts_language_hint=True,
        )

