import os

from nota_asr_server.config import Settings
from nota_asr_server.services.model_manager import ModelManager


def test_model_manager_configures_project_model_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("MODELSCOPE_CACHE", raising=False)
    model_dir = tmp_path / "models"

    ModelManager(Settings(model_dir=model_dir))

    assert model_dir.is_dir()
    assert os.environ["MODELSCOPE_CACHE"] == str(model_dir)


def test_model_manager_advertises_nano_without_loading_it(tmp_path):
    manager = ModelManager(Settings(model_dir=tmp_path / "models"))

    models = {item["id"]: item for item in manager.list_models()}

    assert models["fun-asr-nano"] == {
        "id": "fun-asr-nano",
        "object": "model",
        "owned_by": "nota",
        "ready": False,
        "capabilities": {
            "languages": ["zh", "en", "ja", "yue"],
            "diarization": True,
            "decoder_hotwords": False,
        },
    }
    assert manager.loaded_models == []
