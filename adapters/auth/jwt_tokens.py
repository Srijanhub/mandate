from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuthClaims:
    user_id: str
    role: str
    email: str | None = None
    phone_number: str | None = None
    display_name: str = ""
    auth_method: str = "jwt"
    iat: int = 0
    exp: int = 0


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def hash_otp_code(*, challenge_id: str, phone_number: str, code: str, secret: str) -> str:
    """Compute keyed HMAC-SHA256 digest of a one-time SMS code."""
    msg = f"{challenge_id}:{phone_number}:{code.strip()}".encode()
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def issue_session_token(
    *,
    user_id: str,
    role: str,
    email: str | None,
    phone_number: str | None,
    display_name: str,
    auth_method: str,
    secret: str,
    ttl_seconds: int = 86_400,
) -> tuple[str, int]:
    """Sign a stateless HS256 JWT access token for an authenticated Mandate user."""
    if not secret:
        raise ValueError("AUTH_JWT_SECRET must not be empty")
    now = int(time.time())
    ttl = max(60, ttl_seconds)
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "email": email,
        "phone_number": phone_number,
        "name": display_name,
        "auth_method": auth_method,
        "iat": now,
        "exp": now + ttl,
    }
    h_b64 = _b64u_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    p_b64 = _b64u_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = _b64u_encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{h_b64}.{p_b64}.{sig}", ttl


def verify_session_token(token: str, *, secret: str) -> AuthClaims:
    """Verify HS256 signature and expiration on a Mandate session JWT."""
    if not secret:
        raise ValueError("AUTH_JWT_SECRET must not be empty")
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT structure")

    h_b64, p_b64, sig_b64 = parts
    try:
        header = json.loads(_b64u_decode(h_b64))
        payload = json.loads(_b64u_decode(p_b64))
    except Exception as exc:
        raise ValueError("Invalid JWT encoding") from exc

    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise ValueError("Unsupported JWT algorithm")
    if not isinstance(payload, dict):
        raise ValueError("Invalid JWT payload")

    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    expected_sig = _b64u_encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("Invalid JWT signature")

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= int(time.time()):
        raise ValueError("Session token has expired")

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise ValueError("Missing JWT subject")

    return AuthClaims(
        user_id=sub,
        role=str(payload.get("role") or "user"),
        email=payload.get("email"),
        phone_number=payload.get("phone_number"),
        display_name=str(payload.get("name") or sub),
        auth_method=str(payload.get("auth_method") or "jwt"),
        iat=int(payload.get("iat") or 0),
        exp=exp,
    )
