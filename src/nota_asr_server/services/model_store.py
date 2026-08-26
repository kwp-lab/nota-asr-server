from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any


EventSink = Callable[[dict[str, Any]], None]


class ModelStoreError(RuntimeError):
    pass


class ModelNotInstalledError(ModelStoreError):
    pass


class ModelIntegrityError(ModelStoreError):
    pass


class ModelLicenseError(ModelStoreError):
    pass


@dataclass(frozen=True)
class Component:
    key: str
    model_id: str
    revision: str
    upstream_commit: str
    snapshot_sha256: str | None
    file_count: int | None
    download_bytes: int
    required_files: tuple[str, ...]
    license: str
    license_url: str


@dataclass(frozen=True)
class ModelDefinition:
    alias: str
    display_name: str
    components: tuple[str, ...]
    license: str
    requires_license_acknowledgement: bool


class ModelCatalog:
    def __init__(self, document: dict[str, Any]) -> None:
        if document.get("schema_version") != 1:
            raise ModelStoreError("Unsupported model catalog schema")
        self.schema_version = 1
        self.components = {
            key: Component(
                key=key,
                model_id=value["model_id"],
                revision=value["revision"],
                upstream_commit=value["upstream_commit"],
                snapshot_sha256=value.get("snapshot_sha256"),
                file_count=value.get("file_count"),
                download_bytes=int(value["download_bytes"]),
                required_files=tuple(value["required_files"]),
                license=value["license"],
                license_url=value["license_url"],
            )
            for key, value in document["components"].items()
        }
        self.models = {
            alias: ModelDefinition(
                alias=alias,
                display_name=value["display_name"],
                components=tuple(value["components"]),
                license=value["license"],
                requires_license_acknowledgement=bool(
                    value["requires_license_acknowledgement"]
                ),
            )
            for alias, value in document["models"].items()
        }

    @classmethod
    def load(cls) -> "ModelCatalog":
        resource = files("nota_asr_server").joinpath("model_catalog.json")
        return cls(json.loads(resource.read_text(encoding="utf-8")))

    def model(self, alias: str) -> ModelDefinition:
        try:
            return self.models[alias]
        except KeyError as exc:
            raise ModelStoreError(f"Unknown model alias: {alias}") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_records(
    root: Path, *, exclude: frozenset[str] = frozenset()
) -> Iterator[str]:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        digest = _file_sha256(path)
        yield f"{relative}\t{path.stat().st_size}\t{digest}"


def snapshot_digest(
    root: Path, *, exclude: frozenset[str] = frozenset()
) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    for record in _snapshot_records(root, exclude=exclude):
        digest.update(record.encode("utf-8"))
        digest.update(b"\n")
        count += 1
        total += int(record.split("\t", 2)[1])
    return digest.hexdigest(), count, total


def _downloaded_size(cache_root: Path, expected_bytes: int) -> int:
    """Report resumable transfer bytes without counting assembled copies."""
    size = sum(
        path.stat().st_size for path in cache_root.rglob("*") if path.is_file()
    )
    return min(size, expected_bytes)


class ModelStore:
    def __init__(
        self,
        root: Path,
        *,
        catalog: ModelCatalog | None = None,
        downloader: Callable[..., str] | None = None,
    ) -> None:
        self.root = root
        self.catalog = catalog or ModelCatalog.load()
        self._downloader = downloader

    @property
    def components_root(self) -> Path:
        return self.root / "components"

    def component_path(self, component_key: str) -> Path:
        component = self.catalog.components[component_key]
        safe_revision = component.revision.replace("/", "_")
        return self.components_root / component.key / safe_revision

    def _marker_path(self, component_key: str) -> Path:
        return self.component_path(component_key) / ".nota-installed.json"

    def component_status(self, component_key: str) -> dict[str, Any]:
        component = self.catalog.components[component_key]
        path = self.component_path(component_key)
        marker_path = self._marker_path(component_key)
        installed = path.is_dir() and marker_path.is_file()
        if installed:
            installed = all((path / relative).is_file() for relative in component.required_files)
        return {
            "key": component_key,
            "installed": installed,
            "path": str(path),
            "revision": component.revision,
        }

    def verify_component(self, component_key: str) -> dict[str, Any]:
        component = self.catalog.components[component_key]
        path = self.component_path(component_key)
        marker_path = self._marker_path(component_key)
        if not path.is_dir() or not marker_path.is_file():
            raise ModelNotInstalledError(f"Model component is not installed: {component_key}")
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelIntegrityError(
                f"Invalid install marker for model component: {component_key}"
            ) from exc
        for relative in component.required_files:
            if not (path / relative).is_file():
                raise ModelIntegrityError(
                    f"Model component {component_key} is missing {relative}"
                )
        digest, file_count, total_bytes = snapshot_digest(
            path, exclude=frozenset({".nota-installed.json"})
        )
        expected = component.snapshot_sha256 or marker.get("snapshot_sha256")
        if not expected or digest != expected:
            raise ModelIntegrityError(
                f"Model component checksum mismatch: {component_key}"
            )
        if component.file_count is not None and file_count != component.file_count:
            raise ModelIntegrityError(
                f"Model component file count mismatch: {component_key}"
            )
        return {
            "key": component_key,
            "installed": True,
            "path": str(path),
            "revision": component.revision,
            "snapshot_sha256": digest,
            "file_count": file_count,
            "bytes": total_bytes,
        }

    def verify_model(self, alias: str) -> dict[str, Any]:
        model = self.catalog.model(alias)
        components = []
        for key in model.components:
            try:
                components.append(self.verify_component(key))
            except ModelStoreError as exc:
                components.append(
                    {"key": key, "installed": False, "error": str(exc)}
                )
        installed = all(item["installed"] for item in components)
        return {
            "schema_version": 1,
            "alias": alias,
            "installed": installed,
            "components": components,
        }

    def reference(self, component_key: str, *, policy: str) -> tuple[str, str | None]:
        component = self.catalog.components[component_key]
        status = self.component_status(component_key)
        if status["installed"]:
            return str(self.component_path(component_key)), None
        if policy == "on_demand":
            return component.model_id, component.revision
        self.verify_component(component_key)
        return str(self.component_path(component_key)), None

    def list_models(self) -> list[dict[str, Any]]:
        result = []
        for alias, model in self.catalog.models.items():
            components = [self.component_status(key) for key in model.components]
            result.append(
                {
                    "alias": alias,
                    "display_name": model.display_name,
                    "installed": all(item["installed"] for item in components),
                    "download_bytes": sum(
                        self.catalog.components[key].download_bytes
                        for key in model.components
                    ),
                    "license": model.license,
                    "requires_license_acknowledgement": (
                        model.requires_license_acknowledgement
                    ),
                    "components": components,
                }
            )
        return result

    def install_model(
        self,
        alias: str,
        *,
        accept_undeclared_license: bool = False,
        event_sink: EventSink | None = None,
    ) -> dict[str, Any]:
        model = self.catalog.model(alias)
        if model.requires_license_acknowledgement and not accept_undeclared_license:
            raise ModelLicenseError(
                "This model has no declared upstream license; explicit acknowledgement is required"
            )
        sink = event_sink or (lambda event: None)
        self.root.mkdir(parents=True, exist_ok=True)
        for component_key in model.components:
            try:
                self.verify_component(component_key)
                sink({"event": "component_skipped", "component": component_key})
                continue
            except ModelStoreError:
                pass
            self._install_component(component_key, sink)
        result = self.verify_model(alias)
        if not result["installed"]:
            raise ModelIntegrityError(f"Model installation did not verify: {alias}")
        return result

    def _install_component(self, component_key: str, sink: EventSink) -> None:
        component = self.catalog.components[component_key]
        download_root = self.root / ".downloads" / component.key
        cache_root = download_root / "cache"
        assembled = download_root / "assembled"
        download_root.mkdir(parents=True, exist_ok=True)
        sink(
            {
                "event": "component_started",
                "component": component_key,
                "total_bytes": component.download_bytes,
            }
        )

        stop_monitor = threading.Event()

        def monitor() -> None:
            last_size = -1
            while not stop_monitor.wait(0.5):
                # ModelScope keeps resumable transfers under cache/. A stale
                # assembled/ tree can be a second full copy after an
                # interrupted verification and must not inflate progress.
                size = _downloaded_size(cache_root, component.download_bytes)
                if size != last_size:
                    sink(
                        {
                            "event": "download_progress",
                            "component": component_key,
                            "downloaded_bytes": size,
                            "total_bytes": component.download_bytes,
                        }
                    )
                    last_size = size

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        try:
            downloader = self._downloader
            if downloader is None:
                from modelscope.hub.snapshot_download import snapshot_download

                downloader = snapshot_download
            with contextlib.redirect_stdout(sys.stderr):
                snapshot = Path(
                    downloader(
                        component.model_id,
                        revision=component.revision,
                        cache_dir=str(cache_root),
                    )
                )
        finally:
            stop_monitor.set()
            monitor_thread.join(timeout=2)

        if assembled.exists():
            shutil.rmtree(assembled)
        shutil.copytree(snapshot, assembled)
        digest, file_count, total_bytes = snapshot_digest(assembled)
        if component.snapshot_sha256 and digest != component.snapshot_sha256:
            raise ModelIntegrityError(
                f"Downloaded snapshot does not match the pinned catalog: {component_key}"
            )
        if component.file_count is not None and file_count != component.file_count:
            raise ModelIntegrityError(
                f"Downloaded snapshot file count does not match the catalog: {component_key}"
            )
        for relative in component.required_files:
            if not (assembled / relative).is_file():
                raise ModelIntegrityError(
                    f"Downloaded component {component_key} is missing {relative}"
                )
        marker = {
            "schema_version": 1,
            "component": component_key,
            "model_id": component.model_id,
            "revision": component.revision,
            "upstream_commit": component.upstream_commit,
            "snapshot_sha256": digest,
            "file_count": file_count,
            "bytes": total_bytes,
            "installed_at": int(time.time()),
        }
        (assembled / ".nota-installed.json").write_text(
            json.dumps(marker, indent=2) + "\n", encoding="utf-8"
        )
        destination = self.component_path(component_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        previous = destination.with_name(destination.name + ".previous")
        if previous.exists():
            shutil.rmtree(previous)
        if destination.exists():
            os.replace(destination, previous)
        os.replace(assembled, destination)
        if previous.exists():
            shutil.rmtree(previous)
        # The completed, verified component is self-contained. Keeping the
        # ModelScope cache would otherwise double persistent disk usage; the
        # staging area is retained only for interrupted downloads.
        shutil.rmtree(download_root)
        sink(
            {
                "event": "component_completed",
                "component": component_key,
                "downloaded_bytes": total_bytes,
                "total_bytes": component.download_bytes,
            }
        )
