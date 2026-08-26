import json

import pytest

from nota_asr_server.services.model_store import (
    _downloaded_size,
    ModelCatalog,
    ModelIntegrityError,
    ModelLicenseError,
    ModelNotInstalledError,
    ModelStore,
    snapshot_digest,
)


def test_download_progress_ignores_assembled_copy_and_is_clamped(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "partial.bin").write_bytes(b"x" * 20)
    assembled = tmp_path / "assembled"
    assembled.mkdir()
    (assembled / "complete.bin").write_bytes(b"x" * 100)

    assert _downloaded_size(cache, 10) == 10


def catalog_for(snapshot, *, acknowledgement=False):
    digest, count, size = snapshot_digest(snapshot)
    return ModelCatalog(
        {
            "schema_version": 1,
            "components": {
                "asr": {
                    "model_id": "owner/model",
                    "revision": "master",
                    "upstream_commit": "abc123",
                    "snapshot_sha256": digest,
                    "file_count": count,
                    "download_bytes": size,
                    "required_files": ["configuration.json", "model.pt"],
                    "license": "undeclared" if acknowledgement else "Apache-2.0",
                    "license_url": "https://example.invalid/model",
                }
            },
            "models": {
                "test-model": {
                    "display_name": "Test Model",
                    "components": ["asr"],
                    "license": "undeclared" if acknowledgement else "Apache-2.0",
                    "requires_license_acknowledgement": acknowledgement,
                }
            },
        }
    )


@pytest.fixture
def fake_snapshot(tmp_path):
    snapshot = tmp_path / "upstream"
    snapshot.mkdir()
    (snapshot / "configuration.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "model.pt").write_bytes(b"model-weights")
    return snapshot


def test_model_install_is_staged_marked_and_verified(tmp_path, fake_snapshot):
    events = []

    def download(model_id, *, revision, cache_dir):
        assert model_id == "owner/model"
        assert revision == "master"
        assert cache_dir.endswith("cache")
        return str(fake_snapshot)

    store = ModelStore(
        tmp_path / "models",
        catalog=catalog_for(fake_snapshot),
        downloader=download,
    )

    result = store.install_model("test-model", event_sink=events.append)

    assert result["installed"] is True
    installed = store.component_path("asr")
    marker = json.loads(
        (installed / ".nota-installed.json").read_text(encoding="utf-8")
    )
    assert marker["snapshot_sha256"] == snapshot_digest(fake_snapshot)[0]
    assert store.reference("asr", policy="explicit") == (str(installed), None)
    assert store.reference("asr", policy="on_demand") == (str(installed), None)
    assert not (store.root / ".downloads" / "asr").exists()
    assert events[0]["event"] == "component_started"
    assert events[-1]["event"] == "component_completed"


def test_model_integrity_detects_corruption(tmp_path, fake_snapshot):
    store = ModelStore(
        tmp_path / "models",
        catalog=catalog_for(fake_snapshot),
        downloader=lambda *args, **kwargs: str(fake_snapshot),
    )
    store.install_model("test-model")
    (store.component_path("asr") / "model.pt").write_bytes(b"corrupted")

    with pytest.raises(ModelIntegrityError, match="checksum"):
        store.verify_component("asr")


def test_explicit_reference_requires_installed_component(tmp_path, fake_snapshot):
    store = ModelStore(tmp_path / "models", catalog=catalog_for(fake_snapshot))

    with pytest.raises(ModelNotInstalledError):
        store.reference("asr", policy="explicit")

    assert store.reference("asr", policy="on_demand") == (
        "owner/model",
        "master",
    )


def test_undeclared_license_requires_explicit_acknowledgement(
    tmp_path, fake_snapshot
):
    store = ModelStore(
        tmp_path / "models",
        catalog=catalog_for(fake_snapshot, acknowledgement=True),
        downloader=lambda *args, **kwargs: str(fake_snapshot),
    )

    with pytest.raises(ModelLicenseError, match="acknowledgement"):
        store.install_model("test-model")

    assert store.install_model(
        "test-model", accept_undeclared_license=True
    )["installed"]
