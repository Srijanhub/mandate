from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request

from apps.api.dependencies import AppContainer, get_container


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if tok:
            return tok
    api_key = request.headers.get("x-api-key")
    if api_key and api_key.strip():
        return api_key.strip()
    return None


def _matches(presented: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    )


async def require_user_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> str:
    """Enforce Bearer/x-api-key authentication when settings.require_auth is True."""
    if not container.settings.require_auth:
        return "user"
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token or x-api-key header")
    if _matches(token, container.settings.api_admin_token):
        return "admin"
    if _matches(token, container.settings.api_user_token):
        return "user"
    raise HTTPException(status_code=401, detail="Invalid API token")


async def require_admin_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> str:
    """Enforce admin-only authentication when settings.require_auth is True."""
    if not container.settings.require_auth:
        return "admin"
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token or x-api-key header")
    if _matches(token, container.settings.api_admin_token):
        return "admin"
    if _matches(token, container.settings.api_user_token):
        raise HTTPException(status_code=403, detail="Admin token required")
    raise HTTPException(status_code=401, detail="Invalid API token")
