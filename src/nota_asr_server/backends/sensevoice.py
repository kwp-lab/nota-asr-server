from nota_asr_server.backends.base import BackendCapabilities
from nota_asr_server.backends.funasr_backend import FunASRBackend


class SenseVoiceBackend(FunASRBackend):
    def __init__(
        self,
        device: str,
        references: dict[str, tuple[str, str | None]] | None = None,
    ) -> None:
        references = references or {
            "sensevoice-small": ("iic/SenseVoiceSmall", "master"),
            "fsmn-vad": (
                "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
                "v2.0.4",
            ),
            "campplus": ("iic/speech_campplus_sv_zh-cn_16k-common", "v2.0.2"),
        }
        model, model_revision = references["sensevoice-small"]
        vad_model, vad_model_revision = references["fsmn-vad"]
        spk_model, spk_model_revision = references["campplus"]
        model_config = {
            "model": model,
            "vad_model": vad_model,
            "vad_kwargs": {"max_single_segment_time": 30000},
            "spk_model": spk_model,
            "spk_mode": "vad_segment",
        }
        if model_revision:
            model_config["model_revision"] = model_revision
        if vad_model_revision:
            model_config["vad_model_revision"] = vad_model_revision
        if spk_model_revision:
            model_config["spk_model_revision"] = spk_model_revision
        super().__init__(
            alias="sensevoice",
            device=device,
            model_config=model_config,
            capabilities=BackendCapabilities(
                languages=("zh", "en", "ja", "ko", "yue"),
                diarization=True,
                decoder_hotwords=False,
            ),
            accepts_language_hint=True,
            generate_config={"use_itn": True},
        )
