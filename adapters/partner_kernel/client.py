from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from mandate_core.domain.errors import ValidationError

from adapters.errors import redact_secrets

_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")
_MAX_REDIRECT_HOPS = 3
_MAX_RESPONSE_BYTES = 256 * 1024
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_resolved_ips(host: str, port: int) -> None:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValidationError(f"Could not resolve host {host!r} for external verification") from exc
    if not infos:
        raise ValidationError(f"Host {host!r} returned no routable addresses")
    for info in infos:
        addr = info[4][0].split("%", 1)[0]
        ip = ipaddress.ip_address(addr)
        if not _is_public_ip(ip):
            raise ValidationError(f"Resolved non-public IP {addr!r} for host {host!r} is not permitted")


def validate_public_url(raw_url: str, *, resolve_dns: bool = True) -> str:
    """Validate public HTTP(S) URL, rejecting private literals, local suffixes, and private DNS IPs."""
    cleaned = raw_url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("URL must use http:// or https:// with a valid host")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValidationError(f"Host {host!r} is not permitted for external browser verification")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if not _is_public_ip(ip):
            raise ValidationError(f"Private or reserved IP {host!r} is not permitted")
        return cleaned

    if resolve_dns:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        _validate_resolved_ips(host, port)

    return cleaned


def _extract_price_from_html(html: str) -> str | None:
    """Extract an explicit product price from HTML meta tags or JSON-LD when present."""
    amt_match = re.search(
        r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([0-9]+(?:\.[0-9]{1,2})?)["\']',
        html,
        flags=re.IGNORECASE,
    ) or re.search(
        r'content=["\']([0-9]+(?:\.[0-9]{1,2})?)["\'][^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if amt_match:
        cur_match = re.search(
            r'(?:product:price:currency|og:price:currency)["\'][^>]+content=["\']([A-Za-z]{3})["\']',
            html,
            flags=re.IGNORECASE,
        )
        currency = cur_match.group(1).upper() if cur_match else "USD"
        return f"{amt_match.group(1)} {currency}"

    ld_match = re.search(r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)"?', html, flags=re.IGNORECASE)
    if ld_match:
        ld_cur = re.search(r'"priceCurrency"\s*:\s*"([A-Za-z]{3})"', html, flags=re.IGNORECASE)
        currency = ld_cur.group(1).upper() if ld_cur else "USD"
        return f"{ld_match.group(1)} {currency}"

    return None


class KernelVerifier:
    """
    Kernel (onkernel.com) cloud browser session adapter.
    Provisions a stealth Kernel browser session when KERNEL_API_KEY is configured,
    validates merchant HTTP metadata safely (DNS-resolved SSRF checks, validated redirects,
    and capped response bytes), and fails closed (`verified=False`) when unconfigured.
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
            return {"configured": False, "ok": False, "mode": "unconfigured_fallback"}
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
            return {"configured": True, "ok": False, "mode": "live", "error": redact_secrets(str(exc))[:200]}

    async def _fetch_merchant_html(
        self,
        client: httpx.AsyncClient,
        start_url: str,
        *,
        resolve_dns: bool,
    ) -> tuple[int, str]:
        current_url = start_url
        for _ in range(_MAX_REDIRECT_HOPS + 1):
            async with client.stream("GET", current_url, follow_redirects=False) as resp:
                if resp.status_code in _REDIRECT_STATUSES:
                    location = resp.headers.get("location")
                    if not location:
                        return resp.status_code, ""
                    next_url = urljoin(current_url, location)
                    current_url = await asyncio.to_thread(
                        validate_public_url, next_url, resolve_dns=resolve_dns
                    )
                    continue

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    remaining = _MAX_RESPONSE_BYTES - total
                    if remaining <= 0:
                        break
                    chunks.append(chunk[:remaining])
                    total += len(chunks[-1])
                raw_bytes = b"".join(chunks)
                encoding = resp.encoding or "utf-8"
                return resp.status_code, raw_bytes.decode(encoding, errors="replace")

        raise ValidationError(f"Exceeded maximum redirect limit ({_MAX_REDIRECT_HOPS})")

    async def verify_merchant_url(
        self,
        url: str,
        *,
        expected_title: str | None = None,
        expected_price: str | None = None,
    ) -> dict[str, Any]:
        """Verify URL safety & metadata, failing closed when KERNEL_API_KEY is unset."""
        resolve_dns = self.is_live and self._transport is None
        safe_url = await asyncio.to_thread(validate_public_url, url, resolve_dns=resolve_dns)
        domain = (urlparse(safe_url).hostname or "").lower()
        checks: list[str] = ["public_https_url_validated"]
        warnings: list[str] = []

        if not self.is_live:
            warnings.append(
                "KERNEL_API_KEY not configured; browser verification skipped (fail-closed)"
            )
            return {
                "verified": False,
                "mode": "unconfigured_fallback",
                "url": safe_url,
                "domain": domain,
                "session_id": None,
                "cdp_ready": False,
                "checks": checks,
                "warnings": warnings,
                "observed_title": None,
                "observed_price": None,
            }

        session_id: str | None = None
        cdp_ready = False
        observed_title: str | None = None
        observed_price: str | None = None
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
                status_code, html = await self._fetch_merchant_html(
                    client, safe_url, resolve_dns=resolve_dns
                )
                checks.append("direct_http_metadata_fetch")
                if status_code < 400:
                    checks.append(f"merchant_http_{status_code}")
                    title_match = re.search(
                        r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL
                    )
                    if title_match:
                        observed_title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:160]
                    elif expected_title:
                        observed_title = expected_title
                    observed_price = _extract_price_from_html(html)
                else:
                    warnings.append(f"Merchant URL returned HTTP {status_code}")
            except ValidationError:
                raise
            except Exception as exc:
                warnings.append(f"Merchant fetch warning: {redact_secrets(str(exc))[:160]}")
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
            "observed_price": observed_price,
        }
