import pytest

from nota_asr_server.config import Settings


def test_preload_model_must_be_enabled():
    with pytest.raises(ValueError, match="NOTA_PRELOAD_MODEL"):
        Settings(preload_model="paraformer", enabled_models=("sensevoice",)).validate()


def test_unknown_models_are_rejected():
    with pytest.raises(ValueError, match="Unknown enabled models"):
        Settings(enabled_models=("sensevoice", "other")).validate()

