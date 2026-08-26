# ADR 0016: Generate SBOMs at distribution boundaries

- Status: Accepted
- Date: 2026-08-26
- Decision owners: Nota maintainers

## Context

The repository previously committed one CycloneDX document generated from the
Linux CPU environment. Its serial number includes the `uv.lock` digest and its
metadata includes the project version, so metadata-only changes made the file
stale even when the dependency graph and licenses were unchanged. Windows has
a different dependency graph and already generates separate Python and Rust
SBOMs while packaging the portable Runtime.

An SBOM is a distribution inventory, not a runtime input. Requiring a committed
Linux copy made ordinary Windows-first development depend on access to a Linux
generation environment without improving the accuracy of the Windows package.

## Decision

Do not commit a platform-specific root `bom.cyclonedx.json`.

- The Linux compliance workflow recreates the frozen CPU environment, enforces
  the license policy, generates a CycloneDX SBOM, and uploads it as a workflow
  artifact. The generated file is not compared with a repository copy.
- Docker builds generate `/app/bom.cyclonedx.json` from the environment that is
  actually installed in the image application layer.
- Portable Windows builds continue generating Python and Manager SBOMs inside
  the package's `legal/` directory.
- Wheels and source distributions retain the project license, notice, tracked
  dependency inventory/notices, and model-license guidance; they do not embed a
  stale Linux SBOM.
- Dependency and license-policy changes still run the compliance gate. Tracked
  inventory/notices must be regenerated when their underlying installed package
  or license text changes.

## Alternatives Considered

- **Keep committing the Linux SBOM.** Rejected because project-version and lock
  metadata changes require Linux regeneration even when components are
  unchanged.
- **Remove every SBOM.** Rejected because release-specific inventories remain
  useful for vulnerability analysis and downstream review.
- **Use the Windows SBOM for every target.** Rejected because conditional Python
  dependencies and the native Manager differ from Linux deployments.

## Consequences

Ordinary contributors do not need WSL or Docker merely to refresh an SBOM.
GitHub Actions and Docker builds produce Linux inventories from Linux inputs,
while the owner-local Windows release continues producing Windows inventories.
Workflow artifacts have bounded retention, so a formal Linux release must
attach its generated SBOM to the release if long-term publication is required.

The repository still carries the larger license inventory and notices because
they document reviewed license obligations; SBOM generation does not replace
that review.
