from __future__ import annotations

import hashlib
import secrets

from fastapi import Header, Request

from nota_asr_server.errors import APIError


async def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    keys = request.app.state.settings.api_keys
    if not keys:
        return "anonymous"

    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise APIError(401, "invalid_api_key", "A valid Bearer API key is required")

    if not any(secrets.compare_digest(credential, key) for key in keys):
        raise APIError(401, "invalid_api_key", "A valid Bearer API key is required")
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()
