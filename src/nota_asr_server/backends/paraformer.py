from nota_asr_server.backends.base import BackendCapabilities
from nota_asr_server.backends.funasr_backend import FunASRBackend


class ParaformerBackend(FunASRBackend):
    def __init__(self, device: str) -> None:
        super().__init__(
            alias="paraformer",
            device=device,
            model_config={
                "model": "paraformer-zh",
                "vad_model": "fsmn-vad",
                "punc_model": "ct-punc",
                "spk_model": "cam++",
                "spk_mode": "punc_segment",
            },
            capabilities=BackendCapabilities(
                languages=("zh", "en"),
                diarization=True,
                decoder_hotwords=True,
            ),
            accepts_language_hint=False,
        )
