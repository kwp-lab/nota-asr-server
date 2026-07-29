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

The application is not a multi-tenant authorization system. Deploy separate
instances or add tenant-aware storage, quotas, audit logs, and key ownership
before serving unrelated organizations.

