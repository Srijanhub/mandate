from __future__ import annotations

from typing import Any

from mandate_core.domain.models import (
    Case,
    CaseSnapshot,
    Decision,
    Finding,
    LedgerEntry,
    Mandate,
    Product,
)
from mandate_core.ledger import AgentTrustScore, LedgerVerificationResult
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadyResponse(BaseModel):
    status: str
    paypal_mode: str
    catalog_provider: str
    llm_provider: str


class MandateResponse(BaseModel):
    mandate: Mandate


class MandateDraftResponse(BaseModel):
    mandate: Mandate
    needs_confirm: bool = True


class MandateListResponse(BaseModel):
    mandates: list[Mandate]


class RevokeAllResponse(BaseModel):
    revoked_mandates: list[str]
    cancelled_cases: list[str]
    voided_authorizations: list[str]


class CaseResponse(BaseModel):
    case: Case


class CaseListResponse(BaseModel):
    cases: list[Case]


class WhyResponse(BaseModel):
    case_id: str
    state: str
    plain_english_reasons: list[str]
    blocking_findings: list[Finding]
    warning_findings: list[Finding]
    passed_checks: list[Finding]
    snapshot_diff: list[Finding]


class SnapshotListResponse(BaseModel):
    snapshots: list[CaseSnapshot]


class SnapshotDiffResponse(BaseModel):
    case_id: str
    before: CaseSnapshot | None = None
    after: CaseSnapshot | None = None
    diff: list[Finding] = Field(default_factory=list)
    snapshots_count: int | None = None


class CatalogSearchResponse(BaseModel):
    products: list[Product]


class ProductResponse(BaseModel):
    product: Product


class RankedOptionResponse(BaseModel):
    index: int
    product: Product
    deterministic_score: float
    reason: str
    sanitized_description: str


class ShoppingOptionsResponse(BaseModel):
    mandate_id: str
    options: list[RankedOptionResponse]


class ShoppingAgentResponse(BaseModel):
    mandate_id: str
    tools_exposed: list[str]
    tool_trace: list[dict[str, Any]]
    case: Case | None = None


class LedgerListResponse(BaseModel):
    rows: list[LedgerEntry]
    total_count: int
    lastRow: int


class WebhookResponse(BaseModel):
    accepted: bool
    duplicate: bool
    event_id: str


class EmailPolicyCheckResponse(BaseModel):
    domain: str
    decision: Decision
    ledger_seq: int


__all__ = [
    "AgentTrustScore",
    "CaseListResponse",
    "CaseResponse",
    "CatalogSearchResponse",
    "EmailPolicyCheckResponse",
    "HealthResponse",
    "LedgerListResponse",
    "LedgerVerificationResult",
    "MandateDraftResponse",
    "MandateListResponse",
    "MandateResponse",
    "ProductResponse",
    "RankedOptionResponse",
    "ReadyResponse",
    "RevokeAllResponse",
    "ShoppingAgentResponse",
    "ShoppingOptionsResponse",
    "SnapshotDiffResponse",
    "SnapshotListResponse",
    "WebhookResponse",
    "WhyResponse",
]
