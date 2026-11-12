from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from mandate_core.domain.models import new_id, utcnow
from pydantic import BaseModel, Field

from adapters.auth import (
    generate_otp_code,
    hash_otp_code,
    issue_session_token,
    normalize_e164_phone,
)
from apps.api.auth import (
    AuthIdentity,
    get_optional_identity,
    require_authenticated_identity,
)
from apps.api.dependencies import AppContainer, get_container

router = APIRouter(prefix="/auth", tags=["Authentication"])

_OTP_TTL_SECONDS = 300


class AuthConfigResponse(BaseModel):
    google_enabled: bool
    google_client_id: str | None = None
    google_mode: str
    phone_enabled: bool = True
    phone_mode: str
    demo_otp_exposed: bool
    require_auth: bool


class AuthUserResponse(BaseModel):
    user_id: str
    email: str | None = None
    phone_number: str | None = None
    display_name: str
    avatar_url: str | None = None
    role: str = "user"
    auth_providers: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    mode: str
    user: AuthUserResponse


class GoogleAuthRequest(BaseModel):
    id_token: str | None = Field(default=None, max_length=8192)
    demo_email: str | None = Field(default=None, max_length=320)
    demo_name: str | None = Field(default=None, max_length=160)


class PhoneOtpRequest(BaseModel):
    phone_number: str = Field(min_length=1, max_length=32)


class PhoneOtpRequestResponse(BaseModel):
    challenge_id: str
    phone_number: str
    expires_in_seconds: int
    mode: str
    demo_otp: str | None = None


class PhoneOtpVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=4, max_length=64)
    phone_number: str = Field(min_length=1, max_length=32)
    code: str = Field(min_length=4, max_length=12)
    display_name: str | None = Field(default=None, max_length=160)


class AuthLogoutResponse(BaseModel):
    status: str = "logged_out"


def _build_session_response(
    *,
    user: dict[str, Any],
    mode: str,
    auth_method: str,
    container: AppContainer,
) -> AuthSessionResponse:
    token, expires_in = issue_session_token(
        user_id=user["user_id"],
        role=user["role"],
        email=user.get("email"),
        phone_number=user.get("phone_number"),
        display_name=user["display_name"],
        auth_method=auth_method,
        secret=container.settings.auth_jwt_secret,
        ttl_seconds=container.settings.auth_token_ttl_seconds,
    )
    return AuthSessionResponse(
        access_token=token,
        expires_in=expires_in,
        mode=mode,
        user=AuthUserResponse(**user),
    )


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config(container: AppContainer = Depends(get_container)) -> AuthConfigResponse:
    """Expose public Sign-In capabilities (Google Client ID, phone OTP mode) for the frontend."""
    s = container.settings
    google_live = container.google_verifier.is_live
    sms_live = container.sms_sender.is_live
    return AuthConfigResponse(
        google_enabled=google_live or s.auth_allow_demo_mode,
        google_client_id=s.google_client_id or None,
        google_mode="live" if google_live else ("demo" if s.auth_allow_demo_mode else "disabled"),
        phone_enabled=True,
        phone_mode="twilio" if sms_live else "demo",
        demo_otp_exposed=(not sms_live) and s.auth_expose_demo_otp,
        require_auth=s.require_auth,
    )


@router.post("/google", response_model=AuthSessionResponse)
async def sign_in_with_google(
    body: GoogleAuthRequest,
    identity: AuthIdentity | None = Depends(get_optional_identity),
    container: AppContainer = Depends(get_container),
) -> AuthSessionResponse:
    """Verify Google ID token (or demo email when unconfigured) and issue a Mandate session JWT."""
    verified = await container.google_verifier.verify(
        id_token=body.id_token,
        demo_email=body.demo_email,
        demo_name=body.demo_name,
    )
    link_user_id = identity.user_id if identity and identity.user_id else None
    user = await container.store.upsert_google_user(
        google_sub=verified.google_sub,
        email=verified.email,
        display_name=verified.display_name,
        avatar_url=verified.avatar_url,
        link_user_id=link_user_id,
    )
    await container.store.append_ledger(
        case_id=None,
        mandate_id=None,
        actor=user["user_id"],
        event_type="USER_SIGNED_IN",
        payload={"provider": "google", "mode": verified.mode, "linked": bool(link_user_id)},
    )
    return _build_session_response(
        user=user,
        mode=verified.mode,
        auth_method="google",
        container=container,
    )


@router.post("/phone/request-otp", response_model=PhoneOtpRequestResponse)
async def request_phone_otp(
    body: PhoneOtpRequest,
    container: AppContainer = Depends(get_container),
) -> PhoneOtpRequestResponse:
    """Send a rate-limited, single-use 6-digit SMS OTP code to a mobile number (E.164)."""
    phone = normalize_e164_phone(body.phone_number)
    code = generate_otp_code(6)
    challenge_id = new_id("otp")
    expires_at = utcnow() + timedelta(seconds=_OTP_TTL_SECONDS)
    code_hash = hash_otp_code(
        challenge_id=challenge_id,
        phone_number=phone,
        code=code,
        secret=container.settings.auth_jwt_secret,
    )
    await container.store.create_otp_challenge(
        challenge_id=challenge_id,
        phone_number=phone,
        code_hash=code_hash,
        expires_at=expires_at,
    )
    mode = await container.sms_sender.send_otp(phone_number=phone, code=code)
    exposed = code if (mode == "demo" and container.settings.auth_expose_demo_otp) else None
    return PhoneOtpRequestResponse(
        challenge_id=challenge_id,
        phone_number=phone,
        expires_in_seconds=_OTP_TTL_SECONDS,
        mode=mode,
        demo_otp=exposed,
    )


@router.post("/phone/verify-otp", response_model=AuthSessionResponse)
async def verify_phone_otp(
    body: PhoneOtpVerifyRequest,
    identity: AuthIdentity | None = Depends(get_optional_identity),
    container: AppContainer = Depends(get_container),
) -> AuthSessionResponse:
    """Verify a mobile OTP challenge, upsert user (or link to signed-in session), and issue JWT."""
    phone = normalize_e164_phone(body.phone_number)
    expected_hash = hash_otp_code(
        challenge_id=body.challenge_id.strip(),
        phone_number=phone,
        code=body.code.strip(),
        secret=container.settings.auth_jwt_secret,
    )
    await container.store.verify_otp_challenge(
        challenge_id=body.challenge_id.strip(),
        phone_number=phone,
        expected_hash=expected_hash,
    )
    link_user_id = identity.user_id if identity and identity.user_id else None
    user = await container.store.upsert_phone_user(
        phone_number=phone,
        display_name=body.display_name,
        link_user_id=link_user_id,
    )
    await container.store.append_ledger(
        case_id=None,
        mandate_id=None,
        actor=user["user_id"],
        event_type="USER_SIGNED_IN",
        payload={"provider": "phone", "linked": bool(link_user_id)},
    )
    mode = "twilio" if container.sms_sender.is_live else "demo"
    return _build_session_response(
        user=user,
        mode=mode,
        auth_method="phone",
        container=container,
    )


@router.get("/me", response_model=AuthUserResponse)
async def get_current_user(
    identity: AuthIdentity = Depends(require_authenticated_identity),
    container: AppContainer = Depends(get_container),
) -> AuthUserResponse:
    """Return the currently authenticated Google/Mobile user or static API token identity."""
    if identity.user_id:
        user = await container.store.get_user(identity.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Authenticated user record not found")
        return AuthUserResponse(**user)
    return AuthUserResponse(
        user_id=identity.actor,
        email=identity.email,
        phone_number=identity.phone_number,
        display_name=identity.display_name,
        role=identity.role,
        auth_providers=[identity.auth_method],
    )


@router.post("/logout", response_model=AuthLogoutResponse)
async def logout_session() -> AuthLogoutResponse:
    """Acknowledge client sign-out cleanly."""
    return AuthLogoutResponse()
