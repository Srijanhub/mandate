from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

import httpx
from mandate_core.domain.errors import NotFoundError, PaymentProviderError, ValidationError
from mandate_core.domain.models import Money, PaymentEvidence

PAYPAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def validate_paypal_id(value: str, label: str = "paypal_id") -> str:
    cleaned = value.strip()
    if not PAYPAL_ID_RE.match(cleaned):
        raise ValidationError(f"Invalid {label}: {value!r}")
    return cleaned


def build_readonly_paypal_toolkit(
    client_id: str, client_secret: str, *, sandbox: bool = True
) -> Any:
    """
    Build a strictly read-only PayPalToolkit (orders.get ONLY) so any LLM convenience
    tool is structurally incapable of creating orders or capturing funds.
    """
    from paypal_agent_toolkit.shared.configuration import Configuration, Context

    configuration = Configuration(
        actions={"orders": {"get": True}},
        context=Context(sandbox=sandbox),
    )
    try:
        from paypal_agent_toolkit.openai.toolkit import PayPalToolkit
    except ImportError:
        from paypal_agent_toolkit.langchain.toolkit import PayPalToolkit  # type: ignore[no-redef]
    return PayPalToolkit(client_id=client_id, secret=client_secret, configuration=configuration)


class PayPalPaymentProvider:
    """
    Deterministic PayPal Orders v2 adapter using paypal-agent-toolkit's Configuration/Context
    and direct REST calls with PayPal-Request-Id idempotency. Never handed to an LLM.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        sandbox: bool = True,
        webhook_id: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.sandbox = sandbox
        self.webhook_id = webhook_id
        self.timeout = timeout
        self.base_url = (
            "https://api-m.sandbox.paypal.com" if sandbox else "https://api-m.paypal.com"
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._toolkit_api: Any | None = None

    def get_deterministic_toolkit_api(self) -> Any:
        """Lazily initialize paypal-agent-toolkit's typed PayPalAPI for deterministic calls."""
        if self._toolkit_api is None:
            from paypal_agent_toolkit.shared.configuration import Configuration, Context

            try:
                from paypal_agent_toolkit.openai.toolkit import PayPalToolkit

                config = Configuration(
                    actions={"orders": {"create": True, "get": True, "capture": True}},
                    context=Context(sandbox=self.sandbox),
                )
                toolkit = PayPalToolkit(
                    client_id=self.client_id, secret=self.client_secret, configuration=config
                )
                self._toolkit_api = toolkit.get_paypal_api()
            except Exception:
                self._toolkit_api = None
        return self._toolkit_api

    async def _get_access_token(self, force_refresh: bool = False) -> str:
        async with self._token_lock:
            if not force_refresh and self._token and time.monotonic() < self._token_expires_at:
                return self._token
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/oauth2/token",
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code >= 400:
                    raise PaymentProviderError(
                        f"PayPal OAuth token failed (HTTP {resp.status_code}): {resp.text[:300]}"
                    )
                body = resp.json()
                self._token = body["access_token"]
                expires_in = int(body.get("expires_in", 3600))
                self._token_expires_at = time.monotonic() + max(expires_in - 60, 30)
                return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        request_id: str | None = None,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        refreshed = False
        for attempt in range(3):
            token = await self._get_access_token(force_refresh=False)
            headers: dict[str, str] = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Prefer": "return=representation",
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            if request_id:
                headers["PayPal-Request-Id"] = request_id

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                try:
                    resp = await client.request(
                        method, f"{self.base_url}{path}", headers=headers, json=json_body
                    )
                except httpx.HTTPError as exc:
                    if attempt < 2:
                        await asyncio.sleep(0.2 * (2**attempt))
                        continue
                    raise PaymentProviderError(f"PayPal HTTP transport error: {exc}") from exc

            if resp.status_code == 401 and not refreshed:
                async with self._token_lock:
                    self._token = None
                refreshed = True
                continue

            if resp.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.25 * (2**attempt))
                continue

            if resp.status_code >= 400:
                raise PaymentProviderError(
                    f"PayPal {method} {path} returned HTTP {resp.status_code}: {resp.text[:500]}"
                )

            if not resp.text and allow_empty:
                return {}
            return resp.json()

        raise PaymentProviderError(f"PayPal {method} {path} exhausted retries")

    def _parse_order_evidence(self, raw: dict[str, Any]) -> PaymentEvidence:
        units = raw.get("purchase_units") or []
        if not units:
            raise PaymentProviderError("PayPal order missing purchase_units")
        first = units[0]
        amt = first["amount"]
        payee = first.get("payee") or {}
        payee_id = payee.get("merchant_id") or payee.get("email_address")
        auths = (first.get("payments") or {}).get("authorizations") or []
        caps = (first.get("payments") or {}).get("captures") or []
        links = raw.get("links") or []
        approval_url = next((lk.get("href") for lk in links if lk.get("rel") == "approve"), None)
        return PaymentEvidence(
            provider="paypal",
            order_id=raw["id"],
            authorization_id=auths[0]["id"] if auths else None,
            capture_id=caps[0]["id"] if caps else None,
            intent=raw.get("intent", "AUTHORIZE"),
            status=raw.get("status", "UNKNOWN"),
            amount=Money.of(str(amt["value"]), str(amt["currency_code"])),
            payee_id=payee_id,
            approval_url=approval_url,
            raw=raw,
        )

    async def create_order(
        self,
        *,
        case_id: str,
        amount: Money,
        payee_id: str,
        description: str,
        request_id: str,
    ) -> PaymentEvidence:
        pu: dict[str, Any] = {
            "reference_id": case_id,
            "description": description[:127],
            "amount": {"currency_code": amount.currency, "value": str(amount.amount)},
        }
        if "@" in payee_id:
            pu["payee"] = {"email_address": payee_id}
        elif payee_id:
            pu["payee"] = {"merchant_id": payee_id}

        raw = await self._request(
            "POST",
            "/v2/checkout/orders",
            json_body={"intent": "AUTHORIZE", "purchase_units": [pu]},
            request_id=request_id,
        )
        return self._parse_order_evidence(raw)

    async def get_order(self, order_id: str) -> PaymentEvidence:
        safe_id = validate_paypal_id(order_id, "order_id")
        raw = await self._request("GET", f"/v2/checkout/orders/{safe_id}")
        return self._parse_order_evidence(raw)

    async def authorize_order(self, order_id: str, *, request_id: str) -> PaymentEvidence:
        safe_id = validate_paypal_id(order_id, "order_id")
        raw = await self._request(
            "POST", f"/v2/checkout/orders/{safe_id}/authorize", json_body={}, request_id=request_id
        )
        return self._parse_order_evidence(raw)

    async def capture_authorization(
        self, authorization_id: str, *, request_id: str
    ) -> PaymentEvidence:
        safe_auth = validate_paypal_id(authorization_id, "authorization_id")
        raw = await self._request(
            "POST",
            f"/v2/payments/authorizations/{safe_auth}/capture",
            json_body={"final_capture": True},
            request_id=request_id,
        )
        amt = raw["amount"]
        order_id = (
            (raw.get("supplementary_data") or {}).get("related_ids", {}).get("order_id", safe_auth)
        )
        return PaymentEvidence(
            provider="paypal",
            order_id=order_id,
            authorization_id=safe_auth,
            capture_id=raw["id"],
            intent="AUTHORIZE",
            status=raw.get("status", "COMPLETED"),
            amount=Money.of(str(amt["value"]), str(amt["currency_code"])),
            payee_id=None,
            raw=raw,
        )

    async def void_authorization(self, authorization_id: str, *, request_id: str) -> PaymentEvidence:
        safe_auth = validate_paypal_id(authorization_id, "authorization_id")
        await self._request(
            "POST",
            f"/v2/payments/authorizations/{safe_auth}/void",
            request_id=request_id,
            allow_empty=True,
        )
        return PaymentEvidence(
            provider="paypal",
            order_id=safe_auth,
            authorization_id=safe_auth,
            status="VOIDED",
            amount=Money.zero("USD"),
            payee_id=None,
        )

    async def verify_webhook_signature(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> bool:
        if not self.webhook_id:
            return False
        norm = {k.lower(): v for k, v in headers.items()}
        res = await self._request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            json_body={
                "auth_algo": norm.get("paypal-auth-algo", ""),
                "cert_url": norm.get("paypal-cert-url", ""),
                "transmission_id": norm.get("paypal-transmission-id", ""),
                "transmission_sig": norm.get("paypal-transmission-sig", ""),
                "transmission_time": norm.get("paypal-transmission-time", ""),
                "webhook_id": self.webhook_id,
                "webhook_event": payload,
            },
        )
        return res.get("verification_status") == "SUCCESS"


class MockPayPalProvider:
    """
    Hermetic stateful PayPal Sandbox simulator supporting idempotency, Seller A/B payee
    tampering (Demo Lab R3), amount tampering, authorization holds, capture, void, and webhooks.
    """

    def __init__(self) -> None:
        self._orders: dict[str, PaymentEvidence] = {}
        self._auth_to_order: dict[str, str] = {}
        self._idempotency: dict[str, PaymentEvidence] = {}
        self.expected_webhook_sig = "MOCK_VALID_WEBHOOK_SIG"

    def reset(self) -> None:
        self._orders.clear()
        self._auth_to_order.clear()
        self._idempotency.clear()

    def tamper_order_payee(self, order_id: str, new_payee_id: str) -> PaymentEvidence:
        ev = self._orders.get(order_id)
        if ev is None:
            raise NotFoundError(f"PayPal order {order_id} not found")
        ev.payee_id = new_payee_id
        return ev.model_copy(deep=True)

    def tamper_order_amount(self, order_id: str, new_amount: Money) -> PaymentEvidence:
        ev = self._orders.get(order_id)
        if ev is None:
            raise NotFoundError(f"PayPal order {order_id} not found")
        ev.amount = new_amount
        return ev.model_copy(deep=True)

    async def create_order(
        self,
        *,
        case_id: str,
        amount: Money,
        payee_id: str,
        description: str,
        request_id: str,
    ) -> PaymentEvidence:
        key = f"create:{request_id}"
        if key in self._idempotency:
            return self._idempotency[key].model_copy(deep=True)

        oid = f"ORD-{uuid.uuid4().hex[:12].upper()}"
        ev = PaymentEvidence(
            provider="paypal_mock",
            order_id=oid,
            intent="AUTHORIZE",
            status="APPROVED",
            amount=amount,
            payee_id=payee_id,
            approval_url=f"https://sandbox.paypal.com/checkoutnow?token={oid}",
            raw={"case_id": case_id, "description": description},
        )
        self._orders[oid] = ev
        self._idempotency[key] = ev
        return ev.model_copy(deep=True)

    async def get_order(self, order_id: str) -> PaymentEvidence:
        safe_id = validate_paypal_id(order_id, "order_id")
        ev = self._orders.get(safe_id)
        if ev is None:
            raise NotFoundError(f"PayPal order {safe_id} not found")
        return ev.model_copy(deep=True)

    async def authorize_order(self, order_id: str, *, request_id: str) -> PaymentEvidence:
        key = f"auth:{request_id}"
        if key in self._idempotency:
            return self._idempotency[key].model_copy(deep=True)

        ev = self._orders.get(validate_paypal_id(order_id, "order_id"))
        if ev is None:
            raise NotFoundError(f"PayPal order {order_id} not found")
        if ev.status == "VOIDED":
            raise PaymentProviderError(f"Order {order_id} is VOIDED")
        auth_id = f"AUTH-{uuid.uuid4().hex[:12].upper()}"
        ev.authorization_id = auth_id
        ev.status = "AUTHORIZED"
        self._auth_to_order[auth_id] = ev.order_id
        self._idempotency[key] = ev
        return ev.model_copy(deep=True)

    async def capture_authorization(
        self, authorization_id: str, *, request_id: str
    ) -> PaymentEvidence:
        key = f"cap:{request_id}"
        if key in self._idempotency:
            return self._idempotency[key].model_copy(deep=True)

        safe_auth = validate_paypal_id(authorization_id, "authorization_id")
        oid = self._auth_to_order.get(safe_auth)
        if oid is None:
            raise NotFoundError(f"Authorization {safe_auth} not found")
        ev = self._orders[oid]
        if ev.status == "VOIDED":
            raise PaymentProviderError(f"Cannot capture VOIDED authorization {safe_auth}")
        cap_id = f"CAP-{uuid.uuid4().hex[:12].upper()}"
        ev.capture_id = cap_id
        ev.status = "COMPLETED"
        self._idempotency[key] = ev
        return ev.model_copy(deep=True)

    async def void_authorization(self, authorization_id: str, *, request_id: str) -> PaymentEvidence:
        key = f"void:{request_id}"
        if key in self._idempotency:
            return self._idempotency[key].model_copy(deep=True)

        safe_auth = validate_paypal_id(authorization_id, "authorization_id")
        oid = self._auth_to_order.get(safe_auth)
        if oid is None:
            raise NotFoundError(f"Authorization {safe_auth} not found")
        ev = self._orders[oid]
        if ev.status == "COMPLETED":
            raise PaymentProviderError("Cannot void a COMPLETED capture")
        ev.status = "VOIDED"
        self._idempotency[key] = ev
        return ev.model_copy(deep=True)

    async def verify_webhook_signature(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> bool:
        norm = {k.lower(): v for k, v in headers.items()}
        return (
            bool(norm.get("paypal-transmission-id"))
            and bool(norm.get("paypal-transmission-time"))
            and norm.get("paypal-transmission-sig") == self.expected_webhook_sig
        )
