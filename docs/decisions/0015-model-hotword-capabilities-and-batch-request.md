# ADR 0015: Declare Model Hotword Capabilities and Persist Batch Requests

- Status: Accepted
- Date: 2026-08-25
- Last updated: 2026-08-25

## Context

Paraformer SeACo and Fun-ASR-Nano accept different hotword inputs, while
SenseVoice does not support them. Nota Client needs a stable way to discover
that difference before uploading a meeting and needs retries to use identical
terms.

## Decision

`/v1/models` declares a structured `hotwords` capability while retaining
`decoder_hotwords`. Batch capabilities declare `hotword_request_version=1`.
The optional `hotwords` array is normalized, validated, persisted in
`hotwords_json`, and included in idempotency comparison. Every recovered
window reads the same stored snapshot. Paraformer maps it to decoder `hotword`;
Nano maps it to prompt `hotwords`; SenseVoice returns
`hotwords_not_supported` before upload.

## Alternatives Considered

Server-global hotwords and mutable client lookups were rejected because retry
results would not be reproducible. Reusing `decoder_hotwords` alone was
rejected because it cannot describe Nano prompt support or limits.

## Consequences

The job database contains short-lived meeting terminology until job cleanup.
Technical logs and errors must never contain that text. New fields remain
optional for old clients.

## Compatibility and Evolution

Old clients send no field and behave unchanged. New clients must not send
hotwords unless both request version and selected-model support are declared.
Future context prompting requires a separate capability and field.
