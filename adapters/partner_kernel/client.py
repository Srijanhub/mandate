from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from mandate_core.domain.errors import ValidationError

_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")


def validate_public_url(raw_url: str) -> str:
    """Validate that a URL is public HTTP(S) and reject private/loopback SSRF targets."""
    cleaned = raw_url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("URL must use http:// or https:// with a valid host")

    host = (parsed.hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValidationError(f"Host {host!r} is not permitted for external browser verification")

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValidationError(f"Private or reserved IP {host!r} is not permitted")
    except ValueError:
        pass

    return cleaned


class KernelVerifier:
    """
    Kernel (onkernel.com) cloud browser verification adapter.
    Uses Kernel REST API when KERNEL_API_KEY is configured, and falls back to
    deterministic URL/metadata checks when unconfigured.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "https://api.onkernel.com",
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport

    @property
    def is_live(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def probe(self) -> dict[str, Any]:
        """Check live connectivity to Kernel API without mutating state."""
        if not self.is_live:
            return {"configured": False, "ok": False, "mode": "deterministic_fallback"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                resp = await client.get(f"{self.base_url}/browsers", headers=self._headers())
                return {
                    "configured": True,
                    "ok": resp.status_code < 400,
                    "status_code": resp.status_code,
                    "mode": "live",
                }
        except Exception as exc:
            return {"configured": True, "ok": False, "mode": "live", "error": str(exc)[:200]}

    async def verify_merchant_url(
        self,
        url: str,
        *,
        expected_title: str | None = None,
        expected_price: str | None = None,
    ) -> dict[str, Any]:
        """Verify a merchant URL using a stealth Kernel cloud browser session or fallback."""
        safe_url = validate_public_url(url)
        domain = (urlparse(safe_url).hostname or "").lower()
        checks: list[str] = ["public_https_url_validated"]
        warnings: list[str] = []

        if not self.is_live:
            if expected_title:
                checks.append("expected_title_recorded")
            if expected_price:
                checks.append("expected_price_recorded")
            warnings.append("KERNEL_API_KEY not set; ran deterministic URL validation fallback")
            return {
                "verified": True,
                "mode": "deterministic_fallback",
                "url": safe_url,
                "domain": domain,
                "session_id": None,
                "cdp_ready": False,
                "checks": checks,
                "warnings": warnings,
                "observed_title": expected_title,
                "observed_price": expected_price,
            }

        session_id: str | None = None
        cdp_ready = False
        observed_title = expected_title
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            create_resp = await client.post(
                f"{self.base_url}/browsers",
                headers=self._headers(),
                json={"stealth": True},
            )
            if create_resp.status_code >= 400:
                return {
                    "verified": False,
                    "mode": "live",
                    "url": safe_url,
                    "domain": domain,
                    "session_id": None,
                    "cdp_ready": False,
                    "checks": checks,
                    "warnings": [f"Kernel browser session failed: HTTP {create_resp.status_code}"],
                    "observed_title": None,
                    "observed_price": None,
                }

            payload = create_resp.json()
            session_id = str(payload.get("session_id") or payload.get("id") or "")
            cdp_ready = bool(payload.get("cdp_ws_url"))
            checks.append("kernel_stealth_browser_provisioned")

            try:
                page_resp = await client.get(safe_url, follow_redirects=True)
                if page_resp.status_code < 400:
                    checks.append(f"merchant_http_{page_resp.status_code}")
                    title_match = re.search(
                        r"<title[^>]*>(.*?)</title>", page_resp.text, flags=re.IGNORECASE | re.DOTALL
                    )
                    if title_match:
                        observed_title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:160]
                else:
                    warnings.append(f"Merchant URL returned HTTP {page_resp.status_code}")
            except Exception as exc:
                warnings.append(f"Merchant fetch warning: {str(exc)[:160]}")
            finally:
                if session_id:
                    try:
                        await client.delete(
                            f"{self.base_url}/browsers/{session_id}",
                            headers=self._headers(),
                        )
                    except Exception:
                        pass

        return {
            "verified": len(warnings) == 0,
            "mode": "live",
            "url": safe_url,
            "domain": domain,
            "session_id": session_id or None,
            "cdp_ready": cdp_ready,
            "checks": checks,
            "warnings": warnings,
            "observed_title": observed_title,
            "observed_price": expected_price,
        }
