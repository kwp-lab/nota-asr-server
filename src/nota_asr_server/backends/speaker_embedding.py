from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

import numpy as np


SPEAKER_EMBEDDING_MODEL = "iic/speech_campplus_sv_zh-cn_16k-common"
SPEAKER_EMBEDDING_FINGERPRINT = (
    "cam++:iic/speech_campplus_sv_zh-cn_16k-common:v1"
)


class SpeakerEmbeddingBackend:
    """Lazy CAM++ wrapper with a stable, normalized output contract."""

    def __init__(self, device: str) -> None:
        self.device = device
        self._model: Any = None
        self._load_lock = threading.RLock()
        self._inference_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self.loaded:
            return
        with self._load_lock:
            if self.loaded:
                return
            from funasr import AutoModel

            self._model = AutoModel(
                model=SPEAKER_EMBEDDING_MODEL,
                device=self.device,
                disable_update=True,
                disable_pbar=True,
            )

    def extract(self, audio_path: str) -> tuple[float, ...]:
        self.load()
        with self._inference_lock:
            raw_results = self._model.generate(input=audio_path, batch_size=1)
        return self._normalize_result(raw_results)

    @staticmethod
    def _normalize_result(raw_results: Any) -> tuple[float, ...]:
        if not isinstance(raw_results, list) or not raw_results:
            raise ValueError("CAM++ returned no speaker embedding")
        raw = raw_results[0]
        if not isinstance(raw, Mapping) or raw.get("spk_embedding") is None:
            raise ValueError("CAM++ returned an invalid speaker embedding")

        value = raw["spk_embedding"]
        if hasattr(value, "detach"):
            value = value.detach().cpu().numpy()
        vector = np.asarray(value, dtype=np.float32).squeeze()
        if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
            raise ValueError("CAM++ returned an invalid speaker embedding")
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 1e-12:
            raise ValueError("CAM++ returned a zero speaker embedding")
        normalized = vector / norm
        return tuple(float(item) for item in normalized.tolist())
