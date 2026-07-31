from pathlib import Path

import pytest

from nota_asr_server.config import Settings


def test_preload_model_must_be_enabled():
    with pytest.raises(ValueError, match="NOTA_PRELOAD_MODEL"):
        Settings(preload_model="paraformer", enabled_models=("sensevoice",)).validate()


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
