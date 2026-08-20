from pathlib import Path

import pytest

from nota_asr_server.config import Settings


def test_preload_model_must_be_enabled():
    with pytest.raises(ValueError, match="NOTA_PRELOAD_MODEL"):
        Settings(preload_model="paraformer", enabled_models=("sensevoice",)).validate()


def test_default_model_must_be_enabled():
    with pytest.raises(ValueError, match="NOTA_DEFAULT_MODEL"):
        Settings(default_model="paraformer", enabled_models=("sensevoice",)).validate()


def test_unknown_models_are_rejected():
    with pytest.raises(ValueError, match="Unknown enabled models"):
        Settings(enabled_models=("sensevoice", "other")).validate()


def test_from_env_loads_project_dotenv_and_resolves_model_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NOTA_PRELOAD_MODEL", raising=False)
    monkeypatch.delenv("NOTA_MODEL_DIR", raising=False)
    monkeypatch.delenv("NOTA_DATA_DIR", raising=False)
    (tmp_path / ".env").write_text(
        "NOTA_PRELOAD_MODEL=paraformer\n"
        "NOTA_ENABLED_MODELS=sensevoice,paraformer\n"
        "NOTA_MODEL_DIR=./model-data\n"
        "NOTA_DATA_DIR=./job-data\n",
        encoding="utf-8",
    )

    settings = Settings.from_env()

    assert settings.preload_model == "paraformer"
    assert settings.model_dir == (tmp_path / "model-data").resolve()
    assert settings.data_dir == (tmp_path / "job-data").resolve()


def test_toml_paths_are_relative_to_config_and_environment_overrides(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "portable" / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "server.toml"
    config_path.write_text(
        "schema_version = 1\n"
        "[server]\n"
        "host = '127.0.0.1'\n"
        "port = 8011\n"
        "[models]\n"
        "root = '../models'\n"
        "enabled = ['sensevoice', 'paraformer']\n"
        "default = 'paraformer'\n"
        "preload = 'sensevoice'\n"
        "download_policy = 'explicit'\n"
        "[storage]\n"
        "data_root = '../data'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOTA_PORT", "8022")
    monkeypatch.delenv("NOTA_MODEL_DIR", raising=False)
    monkeypatch.delenv("NOTA_DATA_DIR", raising=False)

    settings = Settings.from_sources(
        config_path,
        cli_overrides={"port": 8033},
        env_file=tmp_path / "missing.env",
    )

    assert settings.port == 8033
    assert settings.default_model == "paraformer"
    assert settings.preload_model == "sensevoice"
    assert settings.model_download_policy == "explicit"
    assert settings.model_dir == (config_dir.parent / "models").resolve()
    assert settings.data_dir == (config_dir.parent / "data").resolve()


def test_environment_overrides_toml(tmp_path, monkeypatch):
    config_path = tmp_path / "server.toml"
    config_path.write_text(
        "schema_version = 1\n"
        "[server]\nport = 8011\n"
        "[models]\nroot = './models'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOTA_PORT", "8022")

    settings = Settings.from_sources(
        config_path, env_file=tmp_path / "missing.env"
    )

    assert settings.port == 8022


def test_explicit_config_uses_only_adjacent_dotenv(tmp_path, monkeypatch):
    runtime = tmp_path / "Runtime With Spaces"
    config_dir = runtime / "config"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "server.toml"
    config_path.write_text(
        "schema_version = 1\n"
        "[server]\nhost = '127.0.0.1'\nport = 8010\n"
        "[models]\nroot = '../models'\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "NOTA_HOST=0.0.0.0\nNOTA_MODEL_DIR=./wrong-models\n", encoding="utf-8"
    )
    (config_dir / ".env").write_text(
        "NOTA_PORT=8123\nNOTA_MODEL_DIR=../external-models\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NOTA_HOST", raising=False)
    monkeypatch.delenv("NOTA_PORT", raising=False)
    monkeypatch.delenv("NOTA_MODEL_DIR", raising=False)

    settings = Settings.from_sources(config_path)

    assert settings.host == "127.0.0.1"
    assert settings.port == 8123
    assert settings.model_dir == (runtime / "external-models").resolve()


def test_toml_requires_supported_schema(tmp_path):
    config_path = tmp_path / "server.toml"
    config_path.write_text("schema_version = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        Settings.from_sources(config_path, env_file=tmp_path / "missing.env")


def test_model_dir_must_not_be_a_file(tmp_path):
    model_file = tmp_path / "models"
    model_file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="NOTA_MODEL_DIR"):
        Settings(model_dir=Path(model_file)).validate()


def test_batch_window_overlap_must_be_smaller_than_window():
    with pytest.raises(ValueError, match="NOTA_BATCH_WINDOW_OVERLAP_SECONDS"):
        Settings(batch_window_seconds=10, batch_window_overlap_seconds=10).validate()


def test_default_meeting_limit_is_four_hours():
    assert Settings().max_audio_seconds == 4 * 60 * 60


def test_nano_is_enabled_by_default():
    assert Settings().enabled_models == (
        "sensevoice",
        "paraformer",
        "fun-asr-nano",
    )


def test_source_deployment_listener_default_is_preserved():
    assert Settings().host == "0.0.0.0"


def test_speaker_embedding_limits_must_form_a_positive_range():
    with pytest.raises(ValueError, match="NOTA_SPEAKER_EMBEDDING_MIN_SECONDS"):
        Settings(speaker_embedding_min_seconds=0).validate()
    with pytest.raises(ValueError, match="NOTA_SPEAKER_EMBEDDING_MAX_SECONDS"):
        Settings(
            speaker_embedding_min_seconds=30,
            speaker_embedding_max_seconds=30,
        ).validate()
