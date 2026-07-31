from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


SUPPORTED_MODELS = ("sensevoice", "paraformer")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8010
    device: str = "cpu"
    preload_model: str = "sensevoice"
    enabled_models: tuple[str, ...] = SUPPORTED_MODELS
    model_dir: Path = Path("models")
    data_dir: Path = Path("data")
    api_keys: tuple[str, ...] = ()
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    max_audio_seconds: int = 4 * 60 * 60
    max_concurrent_inferences: int = 1
    batch_upload_chunk_bytes: int = 8 * 1024 * 1024
    batch_window_seconds: int = 5 * 60
    batch_window_overlap_seconds: int = 2
    batch_job_retention_seconds: int = 24 * 60 * 60
    temp_dir: str | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path.cwd() / ".env", override=False)
        settings = cls(
            host=os.getenv("NOTA_HOST", cls.host),
            port=_env_int("NOTA_PORT", cls.port),
            device=os.getenv("NOTA_DEVICE", cls.device),
            preload_model=os.getenv("NOTA_PRELOAD_MODEL", cls.preload_model),
            enabled_models=_env_csv("NOTA_ENABLED_MODELS", SUPPORTED_MODELS),
            model_dir=_env_path("NOTA_MODEL_DIR", str(cls.model_dir)),
            data_dir=_env_path("NOTA_DATA_DIR", str(cls.data_dir)),
            api_keys=_env_csv("NOTA_API_KEYS", ()),
            max_upload_bytes=_env_int("NOTA_MAX_UPLOAD_BYTES", cls.max_upload_bytes),
            max_audio_seconds=_env_int("NOTA_MAX_AUDIO_SECONDS", cls.max_audio_seconds),
            max_concurrent_inferences=_env_int(
                "NOTA_MAX_CONCURRENT_INFERENCES", cls.max_concurrent_inferences
            ),
            batch_upload_chunk_bytes=_env_int(
                "NOTA_BATCH_UPLOAD_CHUNK_BYTES", cls.batch_upload_chunk_bytes
            ),
            batch_window_seconds=_env_int(
                "NOTA_BATCH_WINDOW_SECONDS", cls.batch_window_seconds
            ),
            batch_window_overlap_seconds=_env_int(
                "NOTA_BATCH_WINDOW_OVERLAP_SECONDS",
                cls.batch_window_overlap_seconds,
            ),
            batch_job_retention_seconds=_env_int(
                "NOTA_BATCH_JOB_RETENTION_SECONDS",
                cls.batch_job_retention_seconds,
            ),
            temp_dir=os.getenv("NOTA_TEMP_DIR") or None,
            log_level=os.getenv("NOTA_LOG_LEVEL", cls.log_level).upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        unknown = sorted(set(self.enabled_models) - set(SUPPORTED_MODELS))
        if unknown:
            raise ValueError(f"Unknown enabled models: {', '.join(unknown)}")
        if not self.enabled_models:
            raise ValueError("NOTA_ENABLED_MODELS must contain at least one model")
        if self.preload_model not in self.enabled_models:
            raise ValueError("NOTA_PRELOAD_MODEL must be listed in NOTA_ENABLED_MODELS")
        if self.model_dir.exists() and not self.model_dir.is_dir():
            raise ValueError("NOTA_MODEL_DIR must be a directory")
        if self.data_dir.exists() and not self.data_dir.is_dir():
            raise ValueError("NOTA_DATA_DIR must be a directory")
        if self.max_upload_bytes <= 0:
            raise ValueError("NOTA_MAX_UPLOAD_BYTES must be positive")
        if self.max_audio_seconds <= 0:
            raise ValueError("NOTA_MAX_AUDIO_SECONDS must be positive")
        if self.max_concurrent_inferences <= 0:
            raise ValueError("NOTA_MAX_CONCURRENT_INFERENCES must be positive")
        if self.batch_upload_chunk_bytes <= 0:
            raise ValueError("NOTA_BATCH_UPLOAD_CHUNK_BYTES must be positive")
        if self.batch_window_seconds <= 0:
            raise ValueError("NOTA_BATCH_WINDOW_SECONDS must be positive")
        if not 0 <= self.batch_window_overlap_seconds < self.batch_window_seconds:
            raise ValueError(
                "NOTA_BATCH_WINDOW_OVERLAP_SECONDS must be non-negative and "
                "smaller than NOTA_BATCH_WINDOW_SECONDS"
            )
        if self.batch_job_retention_seconds <= 0:
            raise ValueError("NOTA_BATCH_JOB_RETENTION_SECONDS must be positive")
