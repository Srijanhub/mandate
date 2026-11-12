from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mandate_core.domain.errors import ValidationError


@dataclass(frozen=True)
class GoogleIdentity:
    google_sub: str
    email: str
    display_name: str
    avatar_url: str | None = None
    mode: str = "live"


class GoogleIdentityVerifier:
    """
    Verifies Google OAuth / Identity Services ID tokens using google-auth.
    Supports deterministic demo Google sign-in ONLY when GOOGLE_CLIENT_ID is unset
    and `allow_demo_mode=True`. Fails closed whenever `GOOGLE_CLIENT_ID` is configured.
    """

    def __init__(
        self,
        *,
        client_id: str = "",
        allow_demo_mode: bool = True,
        verify_fn: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self.allow_demo_mode = allow_demo_mode
        self._verify_fn = verify_fn

    @property
    def is_live(self) -> bool:
        return bool(self.client_id)

    def _default_verify(self, raw_id_token: str, audience: str) -> dict[str, Any]:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        info = google_id_token.verify_oauth2_token(
            raw_id_token,
            google_requests.Request(),
            audience=audience,
        )
        return dict(info)

    async def verify(
        self,
        *,
        id_token: str | None = None,
        demo_email: str | None = None,
        demo_name: str | None = None,
    ) -> GoogleIdentity:
        token = (id_token or "").strip()

        if self.is_live:
            if not token:
                raise ValidationError("Google id_token is required when Google Auth is enabled")
            fn = self._verify_fn or self._default_verify
            try:
                claims = await asyncio.to_thread(fn, token, self.client_id)
            except Exception as exc:
                raise ValidationError(f"Invalid Google ID token: {str(exc)[:160]}") from exc

            sub = str(claims.get("sub") or "").strip()
            email = str(claims.get("email") or "").strip().lower()
            email_verified = claims.get("email_verified")
            if not sub or not email:
                raise ValidationError("Google token missing required subject or email claims")
            if email_verified is False:
                raise ValidationError("Google account email is not verified")

            return GoogleIdentity(
                google_sub=sub,
                email=email,
                display_name=str(claims.get("name") or email.split("@", 1)[0]),
                avatar_url=claims.get("picture"),
                mode="live",
            )

        if not self.allow_demo_mode:
            raise ValidationError("Google Sign-In is not configured (missing GOOGLE_CLIENT_ID)")

        resolved_email = (demo_email or "").strip().lower()
        if not resolved_email and token.startswith("demo-google:"):
            resolved_email = token[len("demo-google:") :].strip().lower()
        if not resolved_email or "@" not in resolved_email:
            raise ValidationError(
                "Provide a valid Google id_token (when configured) or demo_email in demo auth mode"
            )

        sub_hash = hashlib.sha256(resolved_email.encode("utf-8")).hexdigest()[:16]
        return GoogleIdentity(
            google_sub=f"demo-google-{sub_hash}",
            email=resolved_email,
            display_name=(demo_name or "").strip() or resolved_email.split("@", 1)[0],
            avatar_url=None,
            mode="demo",
        )
