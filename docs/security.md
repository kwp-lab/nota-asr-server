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
are never stored. Audio, window checkpoints, private CAM++ trace embeddings,
and final transcript JSON are
deleted after client acknowledgement or the configured retention deadline.
SQLite secure deletion and a truncated WAL checkpoint remove deleted transcript
and window payloads from reusable database pages and the active write-ahead log.
CAM++ traces never appear in API responses or technical logs and follow the
same client-confirmed deletion and retention fallback as their owning job.
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

## Windows Manager boundary

The Windows Runtime template binds only to `127.0.0.1`. The Manager warns when
an operator manually chooses a non-loopback host; it does not add a firewall
rule or imply that a LAN listener is protected. API keys are never written to
`server.toml`, Manager state, uninstall metadata, diagnostics, or manifests.

The Manager starts the Server with a per-process random shutdown token. That
token exists only in the child environment and a private request header used
for graceful shutdown; the internal endpoint is excluded from OpenAPI and
returns 404 without the matching token. The child console is hidden, technical
stdout/stderr are size-rotated, and Manager exit closes a kill-on-close Job
Object after the graceful timeout. An external process answering on the target
port is displayed but never terminated.

Neither JSON diagnostics nor logs may contain audio, transcript text, hotword
text, authorization headers, API keys, or the shutdown token. The FunASR
adapter applies request-scoped sensitive-value filtering because upstream model
code may log inference parameters. Runtime and release manifests contain
versions, Git identity, build mode, architecture, sizes, and hashes only.
