# Security

The application supports Bearer keys through `NOTA_API_KEYS`. Empty keys are
acceptable only for isolated development networks.

Production requirements:

- Terminate TLS at Caddy, Nginx, or an API gateway.
- Configure at least one high-entropy API key.
- Restrict the listener with host firewall or private-network policy.
- Enforce upload size and request timeout at both proxy and application layers.
- Do not log audio content, authorization headers, or transcript bodies.
- Rotate keys and restart the service after changing the environment file.
- Do not expose `/docs` publicly without an intentional gateway policy.

Batch jobs are bound to a SHA-256 fingerprint of the accepted API key; raw keys
are never stored. Audio, window checkpoints, and final transcript JSON are
deleted after client acknowledgement or the configured retention deadline.
SQLite secure deletion and a truncated WAL checkpoint remove deleted transcript
and window payloads from reusable database pages and the active write-ahead log.
Job identifiers are random and authorization failures do not reveal whether a
job exists for another key.

Speaker-embedding requests use the same Bearer boundary. Their temporary WAV
is deleted in a `finally` path after success or failure, and vectors are never
written to server persistence. Routes accept no person name or client-side
participant identifier. Audio bytes and embedding values must not appear in
technical logs.

The application is not a multi-tenant authorization system. Deploy separate
instances or add tenant-aware storage, quotas, audit logs, and key ownership
before serving unrelated organizations.
