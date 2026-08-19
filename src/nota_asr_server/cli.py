from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import uvicorn

from nota_asr_server import __version__
from nota_asr_server.config import Settings
from nota_asr_server.services.model_store import ModelStore, ModelStoreError


SCHEMA_VERSION = 1


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="Path to server.toml")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nota-asr-server")
    parser.add_argument("--version", action="version", version=__version__)
    parser.set_defaults(command="serve")
    commands = parser.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="Start the ASR HTTP server")
    _add_config_argument(serve)
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)

    config = commands.add_parser("config", help="Inspect server configuration")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    validate = config_commands.add_parser("validate")
    _add_config_argument(validate)
    show = config_commands.add_parser("show")
    _add_config_argument(show)
    show.add_argument("--output", choices=("json",), default="json")

    models = commands.add_parser("models", help="Manage model snapshots")
    model_commands = models.add_subparsers(dest="models_command", required=True)
    list_command = model_commands.add_parser("list")
    _add_config_argument(list_command)
    list_command.add_argument("--output", choices=("json",), default="json")
    install = model_commands.add_parser("install")
    install.add_argument("alias")
    _add_config_argument(install)
    install.add_argument("--events", choices=("jsonl",), default="jsonl")
    install.add_argument("--accept-undeclared-license", action="store_true")
    verify = model_commands.add_parser("verify")
    verify.add_argument("alias")
    _add_config_argument(verify)
    verify.add_argument("--output", choices=("json",), default="json")

    doctor = commands.add_parser("doctor", help="Check the local runtime")
    _add_config_argument(doctor)
    doctor.add_argument("--output", choices=("json",), default="json")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    overrides = {
        "host": getattr(args, "host", None),
        "port": getattr(args, "port", None),
    }
    return Settings.from_sources(
        getattr(args, "config", None),
        cli_overrides=overrides,
    )


def _safe_settings(settings: Settings) -> dict[str, Any]:
    payload = asdict(settings)
    payload.pop("api_keys", None)
    for key, value in list(payload.items()):
        if isinstance(value, Path):
            payload[key] = str(value)
        elif isinstance(value, tuple):
            payload[key] = list(value)
    return {"schema_version": SCHEMA_VERSION, "settings": payload}


def _write_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _write_event(payload: dict[str, Any]) -> None:
    _write_json({"schema_version": SCHEMA_VERSION, **payload})
    sys.stdout.flush()


def _serve(args: argparse.Namespace) -> int:
    settings = _settings(args)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    from nota_asr_server.application import create_app

    app = create_app(settings=settings)
    configuration = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(configuration)
    app.state.uvicorn_server = server
    app.state.manager_shutdown_token = os.getenv("NOTA_MANAGER_TOKEN")
    try:
        server.run()
    except KeyboardInterrupt:
        # Python 3.12's asyncio.Runner can re-raise Ctrl+C after Uvicorn has
        # already completed its graceful shutdown. Keep the portable launcher
        # free of a misleading traceback in that normal operator flow.
        pass
    return 0


def _path_check(path: Path) -> dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix="nota-doctor-", delete=True):
            pass
        free_bytes = shutil_disk_free(path)
        return {"path": str(path), "writable": True, "free_bytes": free_bytes}
    except OSError as exc:
        return {"path": str(path), "writable": False, "error": str(exc)}


def shutil_disk_free(path: Path) -> int:
    import shutil

    return shutil.disk_usage(path).free


def _port_check(host: str, port: int) -> dict[str, Any]:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        in_use = sock.connect_ex((probe_host, port)) == 0
    return {"host": host, "port": port, "available": not in_use}


def _model_checks(store: ModelStore) -> list[dict[str, Any]]:
    component_results: dict[str, dict[str, Any]] = {}
    models = store.list_models()
    for model in models:
        verified = True
        for component in model["components"]:
            key = component["key"]
            if not component["installed"]:
                verified = False
                continue
            if key not in component_results:
                try:
                    component_results[key] = store.verify_component(key)
                except ModelStoreError as exc:
                    component_results[key] = {
                        "key": key,
                        "installed": False,
                        "error": str(exc),
                    }
            verified = verified and component_results[key]["installed"]
            if not component_results[key]["installed"]:
                component["error"] = component_results[key]["error"]
        model["verified"] = verified
    return models


def _doctor(settings: Settings) -> dict[str, Any]:
    try:
        import torch

        torch_version = torch.__version__
    except Exception as exc:  # pragma: no cover - depends on broken local runtimes
        torch_version = None
        torch_error = str(exc)
    else:
        torch_error = None
    model_store = ModelStore(settings.model_dir)
    models = _model_checks(model_store)
    port = _port_check(settings.host, settings.port)
    checks = {
        "configuration": {"valid": True, "path": str(settings.config_path or "")},
        "model_directory": _path_check(settings.model_dir),
        "data_directory": _path_check(settings.data_dir),
        "port": port,
        "runtime": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "torch": torch_version,
            "torch_error": torch_error,
            "server": __version__,
        },
        "models": models,
    }
    preload = next(model for model in models if model["alias"] == settings.preload_model)
    healthy = (
        checks["model_directory"].get("writable", False)
        and checks["data_directory"].get("writable", False)
        and port["available"]
        and torch_version is not None
        and preload["verified"]
    )
    return {"schema_version": SCHEMA_VERSION, "ok": healthy, "checks": checks}


def run(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            return _serve(args)

        settings = _settings(args)
        if args.command == "config":
            if args.config_command == "validate":
                _write_json(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "valid": True,
                        "config_path": str(settings.config_path or ""),
                    }
                )
            else:
                _write_json(_safe_settings(settings))
            return 0

        if args.command == "doctor":
            result = _doctor(settings)
            _write_json(result)
            return 0 if result["ok"] else 5

        store = ModelStore(settings.model_dir)
        if args.models_command == "list":
            _write_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "models": store.list_models(),
                }
            )
            return 0
        if args.models_command == "verify":
            result = store.verify_model(args.alias)
            _write_json(result)
            return 0 if result["installed"] else 3
        if args.models_command == "install":
            _write_event({"event": "install_started", "model": args.alias})
            result = store.install_model(
                args.alias,
                accept_undeclared_license=args.accept_undeclared_license,
                event_sink=_write_event,
            )
            _write_event(
                {"event": "install_completed", "model": args.alias, "result": result}
            )
            return 0
        parser.error("Unknown model command")
    except (ValueError, ModelStoreError) as exc:
        event_mode = getattr(args, "events", None) == "jsonl"
        payload = {"event": "error", "error": str(exc)} if event_mode else {
            "schema_version": SCHEMA_VERSION,
            "error": str(exc),
        }
        if event_mode:
            _write_event(payload)
        else:
            _write_json(payload)
        return 3 if isinstance(exc, ModelStoreError) else 2
    except OSError as exc:
        _write_json({"schema_version": SCHEMA_VERSION, "error": str(exc)})
        return 5
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
