import json
from types import SimpleNamespace

from nota_asr_server.cli import run


def write_config(path):
    path.write_text(
        "schema_version = 1\n"
        "[server]\nhost = '127.0.0.1'\nport = 8123\n"
        "[models]\n"
        "root = '../models'\n"
        "enabled = ['sensevoice', 'paraformer', 'fun-asr-nano']\n"
        "default = 'sensevoice'\n"
        "preload = 'sensevoice'\n"
        "download_policy = 'explicit'\n"
        "[storage]\ndata_root = '../data'\n",
        encoding="utf-8",
    )


def test_config_show_emits_versioned_json_without_api_keys(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "server.toml"
    write_config(config)
    monkeypatch.setenv("NOTA_API_KEYS", "secret-key")

    assert run(["config", "show", "--config", str(config)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["settings"]["port"] == 8123
    assert "api_keys" not in payload["settings"]
    assert payload["settings"]["model_dir"] == str((tmp_path / "models").resolve())


def test_config_validate_reports_invalid_schema(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "server.toml"
    config.write_text("schema_version = 2\n", encoding="utf-8")

    assert run(["config", "validate", "--config", str(config)]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert "schema_version" in payload["error"]


def test_serve_treats_ctrl_c_as_clean_shutdown(tmp_path, monkeypatch):
    config = tmp_path / "server.toml"
    write_config(config)
    app = SimpleNamespace(state=SimpleNamespace())

    monkeypatch.setattr(
        "nota_asr_server.application.create_app", lambda *, settings: app
    )

    class InterruptingServer:
        def __init__(self, configuration):
            self.configuration = configuration

        def run(self):
            raise KeyboardInterrupt

    monkeypatch.setattr("nota_asr_server.cli.uvicorn.Server", InterruptingServer)

    assert run(["serve", "--config", str(config)]) == 0
