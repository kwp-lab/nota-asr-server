# ADR 0001: Normalize Model Output Behind a Versioned Contract

- Status: Accepted
- Date: 2026-07-29

## Context

Nota needs to switch between SenseVoice and Paraformer without shipping model-
specific parsing logic in Windows clients. Their raw text tags, punctuation,
language metadata, timestamps, and segmentation behavior differ.

## Decision

All backends return an internal model-independent result. Only the normalizer
can construct the public `verbose_json` schema. The response carries
`schema_version=1.0`; breaking changes require a new version and ADR.

## Consequences

Model upgrades require adapter contract tests. The public schema remains
stable, but segment boundaries and recognition quality are not guaranteed to
be identical across models.

