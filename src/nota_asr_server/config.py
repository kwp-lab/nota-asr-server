from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


SUPPORTED_MODELS = ("sensevoice", "paraformer", "fun-asr-nano")
DOWNLOAD_POLICIES = ("on_demand", "explicit")


def _parse_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _parse_models(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(item.strip() for item in value if item.strip())
    raise ValueError(f"{name} must be a string list or comma-separated string")


def _resolve_path(value: str | os.PathLike[str], base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"Configuration file does not exist: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML configuration: {exc}") from exc
    if document.get("schema_version") != 1:
        raise ValueError("server.toml schema_version must be 1")
    return document


def _section(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a TOML table")
    return value


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8010
    device: str = "cpu"
    default_model: str = "sensevoice"
    preload_model: str = "sensevoice"
    enabled_models: tuple[str, ...] = SUPPORTED_MODELS
    model_dir: Path = Path("models")
    data_dir: Path = Path("data")
    model_download_policy: str = "on_demand"
    api_keys: tuple[str, ...] = ()
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    max_audio_seconds: int = 4 * 60 * 60
    max_concurrent_inferences: int = 1
    batch_upload_chunk_bytes: int = 8 * 1024 * 1024
    batch_window_seconds: int = 5 * 60
    batch_window_overlap_seconds: int = 2
    batch_job_retention_seconds: int = 24 * 60 * 60
    speaker_embedding_max_bytes: int = 2 * 1024 * 1024
    speaker_embedding_min_seconds: int = 5
    speaker_embedding_max_seconds: int = 30
    temp_dir: str | None = None
    log_level: str = "INFO"
    config_path: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls.from_sources()

    @classmethod
    def from_sources(
        cls,
        config_path: str | os.PathLike[str] | None = None,
        *,
        cli_overrides: dict[str, Any] | None = None,
        env_file: str | os.PathLike[str] | None = None,
    ) -> "Settings":
        working_dir = Path.cwd()
        configured_from_process = config_path or os.getenv("NOTA_CONFIG_FILE")
        if env_file:
            selected_env_file = _resolve_path(env_file, working_dir)
        elif configured_from_process:
            selected_env_file = (
                _resolve_path(configured_from_process, working_dir).parent / ".env"
            )
        else:
            selected_env_file = working_dir / ".env"
        env_file_values = {
            key: value
            for key, value in dotenv_values(selected_env_file).items()
            if value is not None
        }

        configured_path = configured_from_process or env_file_values.get(
            "NOTA_CONFIG_FILE"
        )
        resolved_config_path: Path | None = None
        document: dict[str, Any] = {}
        config_base = working_dir
        if configured_path:
            resolved_config_path = _resolve_path(configured_path, working_dir)
            document = _read_toml(resolved_config_path)
            config_base = resolved_config_path.parent

        values: dict[str, Any] = {
            item.name: item.default
            for item in fields(cls)
            if item.name != "config_path"
        }

        if document:
            server = _section(document, "server")
            models = _section(document, "models")
            storage = _section(document, "storage")
            limits = _section(document, "limits")
            batch = _section(document, "batch")
            speaker = _section(document, "speaker_embeddings")

            scalar_mappings = {
                "host": (server, "host"),
                "port": (server, "port"),
                "device": (server, "device"),
                "log_level": (server, "log_level"),
                "default_model": (models, "default"),
                "preload_model": (models, "preload"),
                "model_download_policy": (models, "download_policy"),
                "max_upload_bytes": (limits, "max_upload_bytes"),
                "max_audio_seconds": (limits, "max_audio_seconds"),
                "max_concurrent_inferences": (
                    limits,
                    "max_concurrent_inferences",
                ),
                "batch_upload_chunk_bytes": (batch, "upload_chunk_bytes"),
                "batch_window_seconds": (batch, "window_seconds"),
                "batch_window_overlap_seconds": (batch, "window_overlap_seconds"),
                "batch_job_retention_seconds": (batch, "job_retention_seconds"),
                "speaker_embedding_max_bytes": (speaker, "max_bytes"),
                "speaker_embedding_min_seconds": (speaker, "min_seconds"),
                "speaker_embedding_max_seconds": (speaker, "max_seconds"),
            }
            integer_fields = {
                "port",
                "max_upload_bytes",
                "max_audio_seconds",
                "max_concurrent_inferences",
                "batch_upload_chunk_bytes",
                "batch_window_seconds",
                "batch_window_overlap_seconds",
                "batch_job_retention_seconds",
                "speaker_embedding_max_bytes",
                "speaker_embedding_min_seconds",
                "speaker_embedding_max_seconds",
            }
            for field_name, (source, key) in scalar_mappings.items():
                if key not in source:
                    continue
                raw = source[key]
                values[field_name] = (
                    _parse_int(field_name, raw)
                    if field_name in integer_fields
                    else raw
                )

            if "enabled" in models:
                values["enabled_models"] = _parse_models(
                    "models.enabled", models["enabled"]
                )
            if "root" in models:
                values["model_dir"] = _resolve_path(models["root"], config_base)
            if "data_root" in storage:
                values["data_dir"] = _resolve_path(storage["data_root"], config_base)
            if "temp_root" in storage:
                raw_temp = storage["temp_root"]
                values["temp_dir"] = (
                    str(_resolve_path(raw_temp, config_base)) if raw_temp else None
                )

        env_mappings = {
            "host": "NOTA_HOST",
            "port": "NOTA_PORT",
            "device": "NOTA_DEVICE",
            "default_model": "NOTA_DEFAULT_MODEL",
            "preload_model": "NOTA_PRELOAD_MODEL",
            "enabled_models": "NOTA_ENABLED_MODELS",
            "model_dir": "NOTA_MODEL_DIR",
            "data_dir": "NOTA_DATA_DIR",
            "model_download_policy": "NOTA_MODEL_DOWNLOAD_POLICY",
            "api_keys": "NOTA_API_KEYS",
            "max_upload_bytes": "NOTA_MAX_UPLOAD_BYTES",
            "max_audio_seconds": "NOTA_MAX_AUDIO_SECONDS",
            "max_concurrent_inferences": "NOTA_MAX_CONCURRENT_INFERENCES",
            "batch_upload_chunk_bytes": "NOTA_BATCH_UPLOAD_CHUNK_BYTES",
            "batch_window_seconds": "NOTA_BATCH_WINDOW_SECONDS",
            "batch_window_overlap_seconds": "NOTA_BATCH_WINDOW_OVERLAP_SECONDS",
            "batch_job_retention_seconds": "NOTA_BATCH_JOB_RETENTION_SECONDS",
            "speaker_embedding_max_bytes": "NOTA_SPEAKER_EMBEDDING_MAX_BYTES",
            "speaker_embedding_min_seconds": "NOTA_SPEAKER_EMBEDDING_MIN_SECONDS",
            "speaker_embedding_max_seconds": "NOTA_SPEAKER_EMBEDDING_MAX_SECONDS",
            "temp_dir": "NOTA_TEMP_DIR",
            "log_level": "NOTA_LOG_LEVEL",
        }
        integer_fields = {
            "port",
            "max_upload_bytes",
            "max_audio_seconds",
            "max_concurrent_inferences",
            "batch_upload_chunk_bytes",
            "batch_window_seconds",
            "batch_window_overlap_seconds",
            "batch_job_retention_seconds",
            "speaker_embedding_max_bytes",
            "speaker_embedding_min_seconds",
            "speaker_embedding_max_seconds",
        }
        for field_name, env_name in env_mappings.items():
            raw = os.getenv(env_name)
            environment_base = working_dir
            if raw is None:
                raw = env_file_values.get(env_name)
                environment_base = selected_env_file.parent
            if raw is None:
                continue
            if field_name in integer_fields:
                values[field_name] = _parse_int(env_name, raw)
            elif field_name in {"enabled_models", "api_keys"}:
                values[field_name] = _parse_models(env_name, raw)
            elif field_name in {"model_dir", "data_dir"}:
                values[field_name] = _resolve_path(raw, environment_base)
            elif field_name == "temp_dir":
                values[field_name] = (
                    str(_resolve_path(raw, environment_base)) if raw.strip() else None
                )
            else:
                values[field_name] = raw

        for field_name, raw in (cli_overrides or {}).items():
            if raw is None:
                continue
            if field_name not in values:
                raise ValueError(f"Unknown CLI setting override: {field_name}")
            values[field_name] = (
                _parse_int(field_name, raw) if field_name in integer_fields else raw
            )

        values["log_level"] = str(values["log_level"]).upper()
        settings = cls(**values, config_path=resolved_config_path)
        settings.validate()
        return settings

    def validate(self) -> None:
        unknown = sorted(set(self.enabled_models) - set(SUPPORTED_MODELS))
        if unknown:
            raise ValueError(f"Unknown enabled models: {', '.join(unknown)}")
        if not self.enabled_models:
            raise ValueError("NOTA_ENABLED_MODELS must contain at least one model")
        if self.default_model not in self.enabled_models:
            raise ValueError("NOTA_DEFAULT_MODEL must be listed in NOTA_ENABLED_MODELS")
        if self.preload_model not in self.enabled_models:
            raise ValueError("NOTA_PRELOAD_MODEL must be listed in NOTA_ENABLED_MODELS")
        if self.model_download_policy not in DOWNLOAD_POLICIES:
            raise ValueError(
                "NOTA_MODEL_DOWNLOAD_POLICY must be on_demand or explicit"
            )
        if not 1 <= self.port <= 65535:
            raise ValueError("NOTA_PORT must be between 1 and 65535")
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
        if self.speaker_embedding_max_bytes <= 0:
            raise ValueError("NOTA_SPEAKER_EMBEDDING_MAX_BYTES must be positive")
        if self.speaker_embedding_min_seconds <= 0:
            raise ValueError("NOTA_SPEAKER_EMBEDDING_MIN_SECONDS must be positive")
        if self.speaker_embedding_max_seconds <= self.speaker_embedding_min_seconds:
            raise ValueError(
                "NOTA_SPEAKER_EMBEDDING_MAX_SECONDS must be greater than "
                "NOTA_SPEAKER_EMBEDDING_MIN_SECONDS"
            )
