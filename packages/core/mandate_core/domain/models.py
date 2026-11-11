from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .money import Money


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class MandateStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CaseState(StrEnum):
    PROPOSED = "PROPOSED"
    CART_LOCKED = "CART_LOCKED"
    CHECKED = "CHECKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VERIFIED = "VERIFIED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    NEEDS_RECONFIRM = "NEEDS_RECONFIRM"
    EXPIRED = "EXPIRED"
    FLAGGED = "FLAGGED"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class ConflictCode(StrEnum):
    PRICE_DRIFT = "PRICE_DRIFT"
    PAYEE_MISMATCH = "PAYEE_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    QTY_MISMATCH = "QTY_MISMATCH"
    SELLER_CHANGED = "SELLER_CHANGED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"


class Finding(BaseModel):
    code: str
    severity: FindingSeverity
    source: str
    message: str
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    allow: bool
    verdict: Literal["ALLOW", "WARN", "BLOCK"]
    findings: list[Finding] = Field(default_factory=list)
    plain_english_summary: str


class Mandate(BaseModel):
    mandate_id: str = Field(default_factory=lambda: new_id("mnd"))
    version: int = 1
    owner_id: str = "user-1"
    domain: str = "shopping"
    intent_text: str
    max_total: Money
    max_spend_per_day: Money | None = None
    max_spend_per_week: Money | None = None
    max_transactions: int = Field(default=5, ge=1)
    spent_total: Money | None = None
    spent_today: Money | None = None
    spent_this_week: Money | None = None
    tx_count: int = Field(default=0, ge=0)
    allowed_sellers: list[str] = Field(default_factory=list)
    blocked_sellers: list[str] = Field(default_factory=list)
    require_verified_seller: bool = True
    allowed_categories: list[str] = Field(default_factory=list)
    blocked_keywords: list[str] = Field(default_factory=list)
    deliver_by: datetime | None = None
    expires_at: datetime
    # Domain-agnostic policy pack fields (e.g. email-sending agent)
    allowed_recipient_domains: list[str] = Field(default_factory=list)
    max_recipients: int | None = None
    status: MandateStatus = MandateStatus.DRAFT
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Product(BaseModel):
    product_id: str
    title: str
    description: str = ""
    price: Money
    seller_id: str
    seller_name: str
    seller_verified: bool
    payee_id: str
    category: str = "general"
    in_stock: bool = True
    estimated_delivery_days: int = 2
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    proposal_id: str = Field(default_factory=lambda: new_id("prop"))
    mandate_id: str
    agent_id: str = "shopping-agent"
    product_id: str
    title: str
    quantity: int = Field(default=1, ge=1)
    claimed_unit_price: Money
    claimed_total: Money
    claimed_seller_id: str
    claimed_payee_id: str
    category: str | None = None
    estimated_delivery_at: datetime | None = None
    rationale: str = ""
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class EmailProposal(BaseModel):
    """Second policy-pack payload proving Mandate Core is domain-agnostic."""

    proposal_id: str = Field(default_factory=lambda: new_id("email"))
    mandate_id: str
    subject: str
    recipients: list[str]
    body_preview: str = ""


class PaymentEvidence(BaseModel):
    provider: str = "paypal"
    order_id: str
    authorization_id: str | None = None
    capture_id: str | None = None
    intent: Literal["AUTHORIZE", "CAPTURE"] = "AUTHORIZE"
    status: str
    amount: Money
    payee_id: str | None = None
    approval_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CaseSnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: new_id("snap"))
    case_id: str
    checkpoint: str
    mandate_id: str
    mandate_version: int
    product_id: str
    title: str
    quantity: int
    unit_price: Money
    total_amount: Money
    seller_id: str
    seller_name: str
    seller_verified: bool
    payee_id: str
    in_stock: bool
    category: str
    estimated_delivery_at: datetime | None = None
    paypal_order_id: str | None = None
    paypal_authorization_id: str | None = None
    paypal_capture_id: str | None = None
    sources_used: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class Case(BaseModel):
    case_id: str = Field(default_factory=lambda: new_id("case"))
    mandate_id: str
    mandate_version: int = 1
    state: CaseState = CaseState.PROPOSED
    proposal: Proposal
    approved_snapshot_id: str | None = None
    latest_snapshot_id: str | None = None
    paypal_order_id: str | None = None
    paypal_authorization_id: str | None = None
    paypal_capture_id: str | None = None
    hold_expires_at: datetime | None = None
    last_findings: list[Finding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RecheckJob(BaseModel):
    job_id: str = Field(default_factory=lambda: new_id("job"))
    case_id: str
    checkpoint: str
    status: Literal["PENDING", "RUNNING", "DONE", "FAILED"] = "PENDING"
    run_after: datetime = Field(default_factory=utcnow)
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class LedgerEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("led"))
    seq: int
    case_id: str | None = None
    mandate_id: str | None = None
    actor: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str
    created_at: datetime = Field(default_factory=utcnow)


class AuditVerdict(BaseModel):
    verdict: Literal["ok", "flag", "block"]
    reasons: list[str] = Field(default_factory=list)
