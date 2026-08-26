# Open-source compliance

## Scope

Nota ASR Server is MIT licensed. Third-party Python packages, operating-system
packages, container base layers, and downloaded model weights retain their own
licenses.

## Reproducible Python inventory and on-demand SBOM

The supported release deployment is Linux CPU, represented by the `cpu`
project extra and the committed `uv.lock`. The repository tracks the reviewed
dependency inventory and complete notices, but does not commit a
platform-specific root SBOM. CI generates the Linux SBOM from its frozen
environment and uploads it as a workflow artifact:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e UV_PROJECT_ENVIRONMENT=/tmp/nota-license-venv \
  ghcr.io/astral-sh/uv:0.9.2-python3.12-bookworm-slim sh -lc \
  'uv sync --frozen --no-dev --extra cpu && uv run --no-sync python \
  scripts/generate_license_artifacts.py \
  --python /tmp/nota-license-venv/bin/python --check \
  --sbom-output /workspace/dist/nota-asr-server-linux-python.bom.cyclonedx.json'
```

Ordinary contributors do not need to run this command merely because the
project version or lock-file digest changed. Do not regenerate the tracked
inventory and notices from a Windows environment: optional
platform dependencies differ (`colorama` on Windows and `uvloop` on Linux).
The generator preserves the selected virtual-environment entry point instead
of resolving its Python symlink, so it cannot accidentally inspect CI runner
packages. It uses pinned `pip-licenses 5.5.5`, applies
`scripts/license-policy.json`, verifies reviewed exceptions, and maintains:

- `THIRD_PARTY_LICENSES.md`: package/version/license inventory;
- `THIRD_PARTY_NOTICES.txt`: full installed license texts;
- the CI artifact: an ephemeral CycloneDX 1.6 Linux Python SBOM.

The Dockerfile generates `/app/bom.cyclonedx.json` after installing its frozen
Python environment. A formal Linux release must attach the corresponding CI or
build-generated SBOM to the release instead of copying a repository snapshot.

The portable Windows CPU Runtime is a separate release inventory. Its local
builder calls the same policy generator with `--output-dir` against the
self-contained Windows interpreter and writes Windows-specific
`THIRD_PARTY_LICENSES.md`, `THIRD_PARTY_NOTICES.txt`, and
`bom.cyclonedx.json` under the Runtime's `legal/` directory. Those files must
not replace or masquerade as a Linux CPU inventory.

The release builder also records CPython 3.12.12 from Astral
`python-build-standalone`, the uv version used to assemble it, and the bundled
project license/notice. `cargo metadata --locked` drives a separate Rust
Manager inventory, full available crate license texts/notices, and CycloneDX
SBOM. Windows PowerShell compression and, when used, Windows SDK signing tools
are build tools recorded in the release manifest rather than merged into either
dependency graph. They are not distributed as dependencies inside the ZIP.

CI recreates the environment with `--frozen`, fails when the license policy or
tracked inventory/notices differ, and generates the SBOM without comparing it
to a committed copy. Unknown, AGPL, SSPL, BUSL, GPL-3.0, and unreviewed LGPL
packages must not be accepted implicitly. A necessary exception must name one
exact package version, rationale, upstream source, and verified installed
license text.

## Distribution boundaries

- The wheel and source distribution include the project license, notice,
  third-party notices, inventory, and model-license guidance through PEP 639
  `license-files` metadata. Their SBOM is generated alongside a formal release
  rather than embedded from the repository.
- The Docker image installs the frozen `cpu` extra, retains the legal files
  under `/app`, and generates its Linux Python SBOM during the image build.
- The Python SBOM does not describe `python:3.12-slim`, Debian packages,
  FFmpeg, libsndfile, or their transitive native libraries. Before publishing
  an image, scan the final image into a separate OCI SBOM and review its
  licenses and CVEs. A source checkout or Python SBOM is not a substitute.
- Model snapshots are downloaded at runtime and governed by
  `MODEL_LICENSES.md`; they are never relicensed as MIT by this project.
- The portable Windows ZIP embeds the complete CPU Runtime and the native
  Manager but no model snapshot. Its Python, Rust, CPython, project, and
  model-guidance files remain visibly separate under `legal/`.

```mermaid
flowchart LR
    L["uv.lock + cpu extra"] --> E["Frozen production environment"]
    E --> P["pip-licenses policy check"]
    P --> N["Tracked notices + inventory"]
    P --> S["Generated Linux Python SBOM"]
    N --> W["Wheel / sdist"]
    S --> A["CI / release artifact"]
    N --> D["Docker application layer"]
    S --> D
    D --> O["Separate final-image SBOM before publication"]
    M["Runtime model downloads"] --> ML["MODEL_LICENSES.md review"]
    L --> WR["Windows locked CPU environment"]
    WR --> WN["Windows Python notices + SBOM"]
    C["Cargo.lock + cargo metadata"] --> RN["Manager notices + Rust SBOM"]
    WN --> Z["Portable Windows ZIP"]
    RN --> Z
```
