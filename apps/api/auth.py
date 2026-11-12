from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from mandate_core.domain.errors import AuthorizationError
from mandate_core.domain.models import Mandate

from adapters.auth import verify_session_token
from apps.api.dependencies import AppContainer, get_container


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str | None
    role: str
    actor: str
    email: str | None = None
    phone_number: str | None = None
    display_name: str = "User"
    auth_method: str = "anonymous"


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


def _resolve_token_identity(token: str, container: AppContainer) -> AuthIdentity:
    if _matches(token, container.settings.api_admin_token):
        return AuthIdentity(
            user_id=None,
            role="admin",
            actor="admin",
            display_name="Admin",
            auth_method="static_token",
        )
    if _matches(token, container.settings.api_user_token):
        return AuthIdentity(
            user_id=None,
            role="user",
            actor="user",
            display_name="API User",
            auth_method="static_token",
        )
    try:
        claims = verify_session_token(token, secret=container.settings.auth_jwt_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid API or session token: {exc}") from exc
    return AuthIdentity(
        user_id=claims.user_id,
        role=claims.role,
        actor=claims.user_id,
        email=claims.email,
        phone_number=claims.phone_number,
        display_name=claims.display_name,
        auth_method="jwt",
    )


async def get_optional_identity(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> AuthIdentity | None:
    """Resolve signed-in JWT or static token identity if Authorization/x-api-key is sent."""
    token = _extract_token(request)
    if not token:
        return None
    return _resolve_token_identity(token, container)


async def get_optional_link_identity(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> AuthIdentity | None:
    """Resolve optional identity for login/link routes without letting expired JWTs block re-login."""
    token = _extract_token(request)
    if not token:
        return None
    try:
        return _resolve_token_identity(token, container)
    except HTTPException:
        return None


def scoped_owner_id(identity: AuthIdentity | None) -> str | None:
    """Return user_id when caller is a non-admin authenticated user (strict per-user isolation)."""
    if identity is not None and identity.user_id and identity.role != "admin":
        return identity.user_id
    return None


def assert_mandate_access(mandate: Mandate, identity: AuthIdentity | None) -> None:
    """Reject cross-user access when a non-admin authenticated user touches another user's mandate."""
    owner_id = scoped_owner_id(identity)
    if owner_id is not None and mandate.owner_id != owner_id:
        raise AuthorizationError("Access denied: resource belongs to another user")


async def require_authenticated_identity(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> AuthIdentity:
    """Always require a valid session JWT or static API token (used by /auth/me)."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token or x-api-key header")
    return _resolve_token_identity(token, container)


async def require_user_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> str:
    """Enforce session JWT or Bearer/x-api-key authentication when settings.require_auth is True."""
    token = _extract_token(request)
    if not token:
        if not container.settings.require_auth:
            return "user"
        raise HTTPException(status_code=401, detail="Missing Bearer token or x-api-key header")
    identity = _resolve_token_identity(token, container)
    return identity.role


async def require_admin_auth(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> str:
    """Enforce admin-only authentication when settings.require_auth is True."""
    token = _extract_token(request)
    if not token:
        if not container.settings.require_auth:
            return "admin"
        raise HTTPException(status_code=401, detail="Missing Bearer token or x-api-key header")
    identity = _resolve_token_identity(token, container)
    if identity.role != "admin":
        raise HTTPException(status_code=403, detail="Admin token required")
    return "admin"
