from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import generate_license_artifacts as artifacts


def _packages() -> list[dict[str, object]]:
    return [
        {
            "Name": "example-package",
            "Version": "1.2.3",
            "NormalizedLicense": "MIT",
            "LicenseText": "Example MIT license text",
            "NoticeText": "",
            "URL": "https://example.invalid/package",
        }
    ]


def _prepare_generator(monkeypatch, tmp_path: Path) -> Path:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    packages = _packages()
    monkeypatch.setattr(artifacts, "run_pip_licenses", lambda _python: packages)
    monkeypatch.setattr(artifacts, "validate", lambda values: values)
    monkeypatch.setattr(
        artifacts,
        "OUTPUTS",
        {
            "inventory": tmp_path / "THIRD_PARTY_LICENSES.md",
            "notices": tmp_path / "THIRD_PARTY_NOTICES.txt",
        },
    )
    return python


def test_check_generates_ephemeral_sbom_without_a_committed_copy(
    monkeypatch, tmp_path: Path
) -> None:
    python = _prepare_generator(monkeypatch, tmp_path)
    packages = _packages()
    artifacts.write_or_check(
        artifacts.OUTPUTS["inventory"], artifacts.inventory(packages), False
    )
    artifacts.write_or_check(
        artifacts.OUTPUTS["notices"], artifacts.notices(packages), False
    )
    sbom_path = tmp_path / "artifacts" / "linux.bom.cyclonedx.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_license_artifacts.py",
            "--python",
            str(python),
            "--check",
            "--sbom-output",
            str(sbom_path),
        ],
    )

    artifacts.main()

    document = json.loads(sbom_path.read_text(encoding="utf-8"))
    assert document["bomFormat"] == "CycloneDX"
    assert [component["name"] for component in document["components"]] == [
        "example-package"
    ]
    assert not (tmp_path / "bom.cyclonedx.json").exists()


def test_platform_output_directory_still_contains_a_complete_legal_bundle(
    monkeypatch, tmp_path: Path
) -> None:
    python = _prepare_generator(monkeypatch, tmp_path)
    output_dir = tmp_path / "windows-legal"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_license_artifacts.py",
            "--python",
            str(python),
            "--output-dir",
            str(output_dir),
        ],
    )

    artifacts.main()

    assert {path.name for path in output_dir.iterdir()} == {
        "THIRD_PARTY_LICENSES.md",
        "THIRD_PARTY_NOTICES.txt",
        "bom.cyclonedx.json",
    }
