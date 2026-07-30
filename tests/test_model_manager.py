import os

from nota_asr_server.config import Settings
from nota_asr_server.services.model_manager import ModelManager


def test_model_manager_configures_project_model_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("MODELSCOPE_CACHE", raising=False)
    model_dir = tmp_path / "models"

    ModelManager(Settings(model_dir=model_dir))

    assert model_dir.is_dir()
    assert os.environ["MODELSCOPE_CACHE"] == str(model_dir)
