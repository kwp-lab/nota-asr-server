# ADR 0004: Project-Local Model Storage

## Status

Accepted.

## Context

ModelScope defaults to a cache below the service user's home directory. That
makes a Nota deployment's model inventory harder to discover, back up, and
migrate, and different service users receive independent caches.

## Decision

Nota exposes `NOTA_MODEL_DIR` and defaults it to `./models`. The server resolves
the path at startup and sets ModelScope's `MODELSCOPE_CACHE` before loading any
FunASR model. The repository-local `.env` records the selected preload model,
enabled model aliases, and model directory. A tracked `.env.example` defines
the safe defaults, while `.env` and model weights remain untracked.

Docker Compose bind-mounts the host's `./models` directory into the same path
used by the application inside the container.

## Consequences

- Model files are easy to locate and can be migrated with project data.
- Separate checkouts no longer share one implicit user-level cache.
- Model weights must be copied separately from Git and consume disk per
  checkout unless operators intentionally share the configured directory.
