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
    notifier_provider: str = "console"
    integrations_configured: dict[str, bool] = Field(default_factory=dict)


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


class IntegrationServiceStatus(BaseModel):
    name: str
    configured: bool
    mode: str
    live_ok: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class IntegrationsStatusResponse(BaseModel):
    probed: bool
    services: list[IntegrationServiceStatus]


class KernelVerifyUrlRequest(BaseModel):
    url: str | None = None
    product_id: str | None = None


class KernelVerifyUrlResponse(BaseModel):
    verified: bool
    mode: str
    url: str
    domain: str
    session_id: str | None = None
    cdp_ready: bool = False
    checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    observed_title: str | None = None
    observed_price: str | None = None
    product_id: str | None = None


class ElasticSyncResponse(BaseModel):
    mode: str
    catalog_indexed: int
    ledger_indexed: int
    errors: bool


class ElasticSearchHit(BaseModel):
    id: str
    score: float
    source: dict[str, Any]


class ElasticSearchResponse(BaseModel):
    mode: str
    index: str
    total: int
    hits: list[ElasticSearchHit]


class RenderWorkflowTriggerRequest(BaseModel):
    task_slug: str | None = None
    input_args: list[Any] = Field(default_factory=list)
    run_local_recheck: bool = True


class RenderWorkflowRunResponse(BaseModel):
    run_id: str
    task_slug: str
    status: str
    mode: str
    started_at: str | None = None
    input: list[Any] = Field(default_factory=list)
    results: dict[str, Any] = Field(default_factory=dict)


class ZapierTestRequest(BaseModel):
    event: str = "MANDATE_TEST_NOTIFICATION"
    case_id: str | None = None
    message: str = "Mandate firewall Zapier webhook connectivity test"
    details: dict[str, Any] = Field(default_factory=dict)


class ZapierTestResponse(BaseModel):
    delivered: bool
    mode: str
    event: str


class BryntumResource(BaseModel):
    id: str
    name: str
    role: str
    meta: dict[str, Any] = Field(default_factory=dict)


class BryntumEvent(BaseModel):
    id: str
    resourceId: str
    name: str
    startDate: str
    endDate: str
    status: str
    eventColor: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class BryntumTimelineResponse(BaseModel):
    format: str = "bryntum-scheduler-v1"
    resources: list[BryntumResource]
    events: list[BryntumEvent]


__all__ = [
    "AgentTrustScore",
    "BryntumEvent",
    "BryntumResource",
    "BryntumTimelineResponse",
    "CaseListResponse",
    "CaseResponse",
    "CatalogSearchResponse",
    "ElasticSearchHit",
    "ElasticSearchResponse",
    "ElasticSyncResponse",
    "EmailPolicyCheckResponse",
    "HealthResponse",
    "IntegrationServiceStatus",
    "IntegrationsStatusResponse",
    "KernelVerifyUrlRequest",
    "KernelVerifyUrlResponse",
    "LedgerListResponse",
    "LedgerVerificationResult",
    "MandateDraftResponse",
    "MandateListResponse",
    "MandateResponse",
    "ProductResponse",
    "RankedOptionResponse",
    "ReadyResponse",
    "RenderWorkflowRunResponse",
    "RenderWorkflowTriggerRequest",
    "RevokeAllResponse",
    "ShoppingAgentResponse",
    "ShoppingOptionsResponse",
    "SnapshotDiffResponse",
    "SnapshotListResponse",
    "WebhookResponse",
    "WhyResponse",
    "ZapierTestRequest",
    "ZapierTestResponse",
]
