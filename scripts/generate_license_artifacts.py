from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PIP_LICENSES_VERSION = "5.5.5"
OUTPUTS = {
    "inventory": ROOT / "THIRD_PARTY_LICENSES.md",
    "notices": ROOT / "THIRD_PARTY_NOTICES.txt",
    "sbom": ROOT / "bom.cyclonedx.json",
}


def run_pip_licenses(python: Path) -> list[dict[str, Any]]:
    command = [
        "uvx",
        "--from",
        f"pip-licenses=={PIP_LICENSES_VERSION}",
        "pip-licenses",
        "--python",
        str(python),
        "--format=json",
        "--with-license-file",
        "--with-notice-file",
        "--with-urls",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    packages = json.loads(result.stdout)
    return sorted(
        (item for item in packages if item["Name"] != "nota-asr-server"),
        key=lambda item: (item["Name"].casefold(), item["Version"]),
    )


def normalize_license(expression: str) -> str:
    aliases = {
        "3-Clause BSD License": "BSD-3-Clause",
        "Apache 2.0 License": "Apache-2.0",
        "Apache Software License": "Apache-2.0",
        "BSD License": "BSD-3-Clause",
        "ISC License (ISCL)": "ISC",
        "MIT License": "MIT",
        "MIT License...": "MIT",
        "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
        "Public Domain": "Public domain",
    }
    value = expression.strip()
    for old, new in aliases.items():
        value = value.replace(old, new)
    first_line = value.splitlines()[0].strip()
    if first_line in {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0"}:
        return first_line
    return value


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    policy = json.loads((ROOT / "scripts/license-policy.json").read_text(encoding="utf-8"))
    allowed = set(policy["allowed"])
    prohibited = tuple(policy["prohibited"])
    exceptions = {
        (item["name"].casefold(), item["version"]): item for item in policy["exceptions"]
    }
    used_exceptions: set[tuple[str, str]] = set()

    for package in packages:
        key = (package["Name"].casefold(), package["Version"])
        expression = normalize_license(package["License"])
        exception = exceptions.get(key)
        if exception:
            expression = exception["license"]
            package["LicensePolicyNote"] = exception["reason"]
            package["URL"] = package.get("URL") or exception["source"]
            used_exceptions.add(key)

        if any(token.casefold() in expression.casefold() for token in prohibited):
            raise RuntimeError(
                f"Prohibited license for {package['Name']} {package['Version']}: {expression}"
            )

        identifiers = set(
            re.findall(
                r"(?:Apache-2\.0 WITH LLVM-exception|Public domain|[A-Za-z0-9.-]+)",
                expression,
            )
        )
        identifiers -= {"AND", "OR", "WITH"}
        if not identifiers or (
            not exception and any(identifier not in allowed for identifier in identifiers)
        ):
            raise RuntimeError(
                f"Unreviewed license for {package['Name']} {package['Version']}: {expression}"
            )

        license_text = package.get("LicenseText") or ""
        if not license_text.strip():
            raise RuntimeError(
                f"No installed license text for {package['Name']} {package['Version']}"
            )
        package["NormalizedLicense"] = expression

        if exception:
            digest = sha256_text(license_text.replace("\r\n", "\n").strip() + "\n")
            expected = exception["licenseSha256"]
            if expected != "AUTO" and digest != expected:
                raise RuntimeError(
                    f"License checksum changed for {package['Name']} {package['Version']}: {digest}"
                )
            package["LicenseSha256"] = digest

    unused = set(exceptions) - used_exceptions
    if unused:
        values = ", ".join(f"{name} {version}" for name, version in sorted(unused))
        raise RuntimeError(f"Stale license-policy exceptions: {values}")
    return packages


def inventory(packages: list[dict[str, Any]]) -> str:
    rows = [
        f"| {item['Name']} | {item['Version']} | {item['NormalizedLicense']} | {item.get('URL') or '-'} |"
        for item in packages
    ]
    exceptions = [
        f"- **{item['Name']} {item['Version']}**: {item['LicensePolicyNote']} "
        f"License SHA-256: `{item['LicenseSha256']}`."
        for item in packages
        if item.get("LicensePolicyNote")
    ]
    return "\n".join(
        [
            "# Third-party Python dependency inventory",
            "",
            "Generated with pip-licenses from the locked production CPU environment",
            "(`uv sync --frozen --no-dev --extra cpu`). Model weights and operating-system",
            "packages are outside this Python inventory; see `MODEL_LICENSES.md` and",
            "`docs/open-source-compliance.md`.",
            "",
            "| Package | Version | License | Project URL |",
            "|---|---:|---|---|",
            *rows,
            "",
            "## Reviewed exceptions",
            "",
            *(exceptions or ["None."]),
            "",
        ]
    )


def notices(packages: list[dict[str, Any]]) -> str:
    groups: dict[str, dict[str, Any]] = {}
    for item in packages:
        text = item["LicenseText"].replace("\r\n", "\n").strip()
        digest = sha256_text(text)
        group = groups.setdefault(digest, {"text": text, "packages": []})
        group["packages"].append(
            f"{item['Name']} {item['Version']} ({item['NormalizedLicense']})"
        )

    sections = []
    for group in sorted(groups.values(), key=lambda value: value["packages"][0].casefold()):
        users = "\n".join(f"- {value}" for value in group["packages"])
        sections.append(f"{'-' * 79}\nUsed by:\n{users}\n\n{group['text']}")
    notice_sections = []
    for item in packages:
        notice_text = (item.get("NoticeText") or "").replace("\r\n", "\n").strip()
        if not notice_text or notice_text == "UNKNOWN":
            continue
        notice_sections.append(
            f"{'-' * 79}\nAdditional notice for {item['Name']} {item['Version']}\n\n{notice_text}"
        )
    additional_notices = ""
    if notice_sections:
        additional_notices = (
            "\n\nADDITIONAL UPSTREAM NOTICE FILES\n"
            "================================\n\n"
            + "\n\n".join(notice_sections)
        )
    return (
        "NOTA ASR SERVER THIRD-PARTY NOTICES\n"
        "===================================\n\n"
        + "\n\n".join(sections)
        + additional_notices
        + "\n"
    )


def sbom(packages: list[dict[str, Any]]) -> str:
    lock_digest = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
    serial = (
        f"{lock_digest[:8]}-{lock_digest[8:12]}-4{lock_digest[13:16]}-"
        f"a{lock_digest[17:20]}-{lock_digest[20:32]}"
    )
    components = []
    for item in packages:
        normalized_name = re.sub(r"[-_.]+", "-", item["Name"]).lower()
        purl = f"pkg:pypi/{normalized_name}@{item['Version']}"
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": purl,
            "name": item["Name"],
            "version": item["Version"],
            "licenses": [{"expression": item["NormalizedLicense"]}],
            "purl": purl,
        }
        if item.get("URL"):
            component["externalReferences"] = [{"type": "website", "url": item["URL"]}]
        components.append(component)

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": "pkg:pypi/nota-asr-server",
                "name": "nota-asr-server",
                "version": project["version"],
                "licenses": [{"license": {"id": "MIT"}}],
            },
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "pip-licenses",
                        "version": PIP_LICENSES_VERSION,
                    }
                ]
            },
        },
        "components": components,
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_or_check(path: Path, content: str, check: bool) -> None:
    normalized = content.replace("\r\n", "\n").rstrip() + "\n"
    if check:
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if current != normalized:
            raise RuntimeError(f"{path.name} is stale; regenerate the license artifacts")
    else:
        path.write_text(normalized, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    packages = validate(run_pip_licenses(args.python.resolve()))
    write_or_check(OUTPUTS["inventory"], inventory(packages), args.check)
    write_or_check(OUTPUTS["notices"], notices(packages), args.check)
    write_or_check(OUTPUTS["sbom"], sbom(packages), args.check)
    print("License artifacts are current." if args.check else "License artifacts generated.")


if __name__ == "__main__":
    main()
