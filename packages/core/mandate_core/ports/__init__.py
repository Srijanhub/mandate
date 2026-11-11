from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from mandate_core.domain.models import (
    AuditVerdict,
    CaseSnapshot,
    Mandate,
    Money,
    PaymentEvidence,
    Product,
)


@runtime_checkable
class PaymentProvider(Protocol):
    """Port for payment rails (e.g. PayPal Orders v2)."""

    async def create_order(
        self,
        *,
        case_id: str,
        amount: Money,
        payee_id: str,
        description: str,
        request_id: str,
    ) -> PaymentEvidence: ...

    async def get_order(self, order_id: str) -> PaymentEvidence: ...

    async def authorize_order(self, order_id: str, *, request_id: str) -> PaymentEvidence: ...

    async def capture_authorization(
        self, authorization_id: str, *, request_id: str
    ) -> PaymentEvidence: ...

    async def void_authorization(self, authorization_id: str, *, request_id: str) -> PaymentEvidence: ...

    async def verify_webhook_signature(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> bool: ...


@runtime_checkable
class Catalog(Protocol):
    """Port for product catalog search and fresh item truth lookup."""

    async def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[Product]: ...

    async def get(self, product_id: str) -> Product | None: ...


@runtime_checkable
class LLM(Protocol):
    """Port for advisory/data-producing LLM adapters. Never makes enforcement decisions."""

    async def compile_mandate(self, text: str) -> dict[str, Any]: ...

    async def rank_candidates(
        self,
        *,
        intent_text: str,
        candidates: list[Product],
        limit: int = 5,
    ) -> list[dict[str, str]]: ...

    async def audit_snapshot(
        self,
        *,
        mandate: Mandate,
        snapshot: CaseSnapshot,
        untrusted_product_text: str,
    ) -> AuditVerdict: ...


@runtime_checkable
class Notifier(Protocol):
    """Port for user/operator notifications (console, Zapier MCP, Slack/email)."""

    async def notify(
        self,
        *,
        event: str,
        case_id: str | None,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None: ...
