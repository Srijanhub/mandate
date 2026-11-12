from __future__ import annotations

import logging
import re
import secrets

import httpx
from mandate_core.domain.errors import ValidationError

from adapters.errors import ExternalServiceError

logger = logging.getLogger("mandate.auth.sms")

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_STRIP_SEPARATORS_RE = re.compile(r"[\s().-]+")


def normalize_e164_phone(raw_phone: str) -> str:
    """Normalize and strictly validate a mobile number in E.164 format (e.g. +14155551234)."""
    cleaned = _STRIP_SEPARATORS_RE.sub("", raw_phone.strip())
    if not _E164_RE.match(cleaned):
        raise ValidationError(
            "Phone number must be in international E.164 format (e.g. +14155551234 or +919876543210)"
        )
    return cleaned


def generate_otp_code(length: int = 6) -> str:
    """Generate a cryptographically random numeric OTP code."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


class SmsOtpSender:
    """
    Sends SMS OTP verification codes via Twilio REST API when configured,
    with deterministic demo logging/sandbox mode when Twilio credentials are unset.
    """

    def __init__(
        self,
        *,
        account_sid: str = "",
        auth_token: str = "",
        from_number: str = "",
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.account_sid = account_sid.strip()
        self.auth_token = auth_token.strip()
        self.from_number = from_number.strip()
        self.timeout = timeout
        self._transport = transport

    @property
    def is_live(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number)

    async def send_otp(self, *, phone_number: str, code: str) -> str:
        """Send OTP via Twilio REST or demo console; returns delivery mode ('twilio' | 'demo')."""
        if not self.is_live:
            masked = f"***{phone_number[-4:]}"
            logger.info("DEMO SMS OTP issued for %s", masked)
            return "demo"

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        body = f"Your Mandate verification code is {code}. It expires in 5 minutes."
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                resp = await client.post(
                    url,
                    auth=(self.account_sid, self.auth_token),
                    data={"To": phone_number, "From": self.from_number, "Body": body},
                )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"SMS delivery failed: {type(exc).__name__}") from exc

        if resp.status_code >= 400:
            raise ExternalServiceError(
                f"Twilio SMS rejected (HTTP {resp.status_code})",
                details={"status_code": resp.status_code},
            )
        return "twilio"
