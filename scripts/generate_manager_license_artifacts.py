from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def _third_party_packages(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            package
            for package in metadata["packages"]
            if package["name"] != "nota-asr-manager"
        ),
        key=lambda package: (package["name"].casefold(), package["version"]),
    )


def _license_files(package: dict[str, Any]) -> list[Path]:
    root = Path(package["manifest_path"]).parent
    names = ("LICENSE*", "COPYING*", "NOTICE*")
    paths = {path for pattern in names for path in root.glob(pattern) if path.is_file()}
    return sorted(paths, key=lambda path: path.name.casefold())


def _inventory(packages: list[dict[str, Any]]) -> str:
    lines = [
        "# Nota ASR Manager third-party license inventory",
        "",
        "Generated from the locked Cargo dependency graph used for the Windows Manager.",
        "",
        "| Package | Version | License | Source |",
        "| --- | --- | --- | --- |",
    ]
    for package in packages:
        source = package.get("repository") or package.get("source") or "Cargo package metadata"
        lines.append(
            f"| {package['name']} | {package['version']} | "
            f"{package.get('license') or 'Not declared'} | {source} |"
        )
    return "\n".join(lines) + "\n"


def _notices(packages: list[dict[str, Any]]) -> str:
    blocks = [
        "Nota ASR Manager third-party notices",
        "====================================",
        "",
    ]
    for package in packages:
        blocks.extend(
            [
                f"--- {package['name']} {package['version']} ---",
                f"Declared license: {package.get('license') or 'Not declared'}",
                f"Source: {package.get('repository') or package.get('source') or 'Cargo package metadata'}",
                "",
            ]
        )
        files = _license_files(package)
        if not files:
            blocks.extend(["No license text was present in the packaged Cargo source.", ""])
            continue
        for path in files:
            blocks.extend([f"[{path.name}]", path.read_text(encoding="utf-8", errors="replace").rstrip(), ""])
    return "\n".join(blocks).rstrip() + "\n"


def _sbom(packages: list[dict[str, Any]], version: str, lock_path: Path) -> str:
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    serial = (
        f"{lock_digest[:8]}-{lock_digest[8:12]}-4{lock_digest[13:16]}-"
        f"a{lock_digest[17:20]}-{lock_digest[20:32]}"
    )
    components = []
    for package in packages:
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": f"pkg:cargo/{package['name']}@{package['version']}",
            "name": package["name"],
            "version": package["version"],
            "purl": f"pkg:cargo/{package['name']}@{package['version']}",
        }
        if package.get("license"):
            component["licenses"] = [{"expression": package["license"]}]
        components.append(component)
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": f"pkg:cargo/nota-asr-manager@{version}",
                "name": "nota-asr-manager",
                "version": version,
                "licenses": [{"license": {"id": "MIT"}}],
            }
        },
        "components": components,
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--metadata", type=Path)
    source.add_argument("--manifest-path", type=Path)
    parser.add_argument("--cargo-lock", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.metadata:
        metadata = json.loads(args.metadata.read_text(encoding="utf-8-sig"))
    else:
        result = subprocess.run(
            [
                "cargo",
                "metadata",
                "--manifest-path",
                str(args.manifest_path),
                "--locked",
                "--format-version",
                "1",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        metadata = json.loads(result.stdout)
    packages = _third_party_packages(metadata)
    prohibited = ("AGPL", "GPL-3.0", "SSPL", "BUSL")
    for package in packages:
        expression = package.get("license")
        if not expression:
            raise RuntimeError(
                f"Cargo package {package['name']} {package['version']} has no declared license"
            )
        if any(token.casefold() in expression.casefold() for token in prohibited):
            raise RuntimeError(
                f"Cargo package {package['name']} {package['version']} has prohibited license {expression}"
            )
    manager = next(package for package in metadata["packages"] if package["name"] == "nota-asr-manager")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "MANAGER_THIRD_PARTY_LICENSES.md").write_text(
        _inventory(packages), encoding="utf-8", newline="\n"
    )
    (args.output_dir / "MANAGER_THIRD_PARTY_NOTICES.txt").write_text(
        _notices(packages), encoding="utf-8", newline="\n"
    )
    (args.output_dir / "manager.bom.cyclonedx.json").write_text(
        _sbom(packages, manager["version"], args.cargo_lock),
        encoding="utf-8",
        newline="\n",
    )
    print(f"Manager license artifacts generated for {len(packages)} packages.")


if __name__ == "__main__":
    main()
