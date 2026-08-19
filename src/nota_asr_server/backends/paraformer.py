from nota_asr_server.backends.base import BackendCapabilities
from nota_asr_server.backends.funasr_backend import FunASRBackend


class ParaformerBackend(FunASRBackend):
    def __init__(
        self,
        device: str,
        references: dict[str, tuple[str, str | None]] | None = None,
    ) -> None:
        references = references or {
            "paraformer-seaco": (
                "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
                "v2.0.9",
            ),
            "fsmn-vad": (
                "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
                "v2.0.4",
            ),
            "ct-punc": (
                "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
                "v2.0.4",
            ),
            "campplus": ("iic/speech_campplus_sv_zh-cn_16k-common", "v2.0.2"),
        }
        model, model_revision = references["paraformer-seaco"]
        vad_model, vad_model_revision = references["fsmn-vad"]
        punc_model, punc_model_revision = references["ct-punc"]
        spk_model, spk_model_revision = references["campplus"]
        model_config = {
            "model": model,
            "vad_model": vad_model,
            "punc_model": punc_model,
            "spk_model": spk_model,
            "spk_mode": "punc_segment",
        }
        for key, revision in (
            ("model_revision", model_revision),
            ("vad_model_revision", vad_model_revision),
            ("punc_model_revision", punc_model_revision),
            ("spk_model_revision", spk_model_revision),
        ):
            if revision:
                model_config[key] = revision
        super().__init__(
            alias="paraformer",
            device=device,
            model_config=model_config,
            capabilities=BackendCapabilities(
                languages=("zh", "en"),
                diarization=True,
                decoder_hotwords=True,
            ),
            accepts_language_hint=False,
        )
