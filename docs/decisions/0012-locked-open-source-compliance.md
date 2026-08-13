# ADR 0012: Generate distribution compliance from the locked CPU environment

- Status: Accepted
- Date: 2026-08-13
- Last updated: 2026-08-13
- Decision owners: Nota maintainers

## Context

Nota ASR Server distributes Python packages and a CPU container while model
weights are downloaded separately at runtime. The previous Dockerfile resolved
PyTorch and application dependencies during each build, so a static license
list could not describe the actual image consistently. Python package licenses,
native operating-system packages, and model licenses also have different
distribution boundaries.

## Decision

Define a pinned `cpu` project extra, resolve it in `uv.lock`, and make the CPU
Docker image install that frozen environment. Generate the Python dependency
inventory, complete installed license/notice texts, and CycloneDX SBOM with a
pinned version of `pip-licenses`. Enforce an allowlist plus exact,
checksum-guarded exceptions. Package the legal files in wheels, source
distributions, and the application layer of the container.

Track runtime model terms separately in `MODEL_LICENSES.md`. Do not represent
model weights, the base image, Debian packages, FFmpeg, or libsndfile as covered
by the Python SBOM. A published container image requires an additional scan of
the final OCI filesystem.

## Alternatives Considered

- **Continue installing unpinned PyTorch in Docker.** Rejected because builds
  and compliance inventories would drift.
- **Treat model weights as Python dependencies.** Rejected because they are
  fetched separately and can have independent terms and mutable revisions.
- **Use only a hand-written NOTICE.** Rejected because the large transitive
  environment and upstream notice files cannot be maintained reliably by hand.
- **Claim the Python SBOM describes the whole container.** Rejected because it
  omits native packages and the base image.

## Consequences

CPU dependency changes now update `uv.lock` and generated compliance files
together. Docker builds are more reproducible and reuse a single frozen
environment. The repository carries a large notice file, and model or OCI
redistribution still requires a separate explicit review.

## Compatibility and Evolution

GPU/XPU environments may receive their own named extras, lock resolution, and
SBOMs. They must not reuse the CPU inventory. A future published container
workflow must add a final-image SBOM and policy gate without weakening the
Python or model-license boundaries defined here.
