from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field

from mandate_core.domain.models import Case, CaseSnapshot, CaseState, LedgerEntry, Money
from mandate_core.domain.money import currency_scale
from mandate_core.ledger.chain import canonical_json


class IntentReceiptFacts(BaseModel):
    """Code-verified facts bound into an immutable SHA-256 Intent Receipt."""

    case_id: str
    mandate_id: str
    mandate_version: int
    state: CaseState
    product_id: str
    title: str
    quantity: int
    unit_price: str
    total_amount: str
    currency: str
    seller_id: str
    seller_verified: bool | None = None
    payee_id: str
    latest_snapshot_id: str | None = None
    latest_checkpoint: str | None = None
    approved_snapshot_id: str | None = None
    paypal_order_id: str | None = None
    paypal_authorization_id: str | None = None
    paypal_capture_id: str | None = None
    latest_ledger_seq: int | None = None
    latest_ledger_hash: str | None = None
    findings: list[dict[str, str]] = Field(default_factory=list)


class IntentReceipt(BaseModel):
    """Cryptographic Intent Receipt with optional leak-checked plain-English narrative."""

    facts: IntentReceiptFacts
    narrative: str
    narrative_source: Literal["deterministic-template", "llm-narrated"]
    receipt_hash: str


def _summarize_findings(case: Case) -> list[dict[str, str]]:
    return [
        {
            "code": f.code,
            "severity": f.severity.value,
            "source": f.source,
            "explanation": f.explanation,
        }
        for f in case.last_findings
    ]


def build_receipt_facts(
    *,
    case: Case,
    snapshot: CaseSnapshot | None,
    latest_ledger_entry: LedgerEntry | None,
) -> tuple[IntentReceiptFacts, Money, Money]:
    """
    Build deterministic receipt facts from code-verified Domain & Ledger models.
    Returns (facts, authoritative_total_money, authoritative_unit_money).
    """
    if snapshot is not None:
        unit_money = snapshot.unit_price
        total_money = snapshot.total_amount
        title = snapshot.title
        quantity = snapshot.quantity
        seller_id = snapshot.seller_id
        seller_verified: bool | None = snapshot.seller_verified
        payee_id = snapshot.payee_id
        latest_snapshot_id: str | None = snapshot.snapshot_id
        latest_checkpoint: str | None = snapshot.checkpoint
        order_id = case.paypal_order_id or snapshot.paypal_order_id
        auth_id = case.paypal_authorization_id or snapshot.paypal_authorization_id
        capture_id = case.paypal_capture_id or snapshot.paypal_capture_id
    else:
        unit_money = case.proposal.claimed_unit_price
        total_money = case.proposal.claimed_total
        title = case.proposal.title
        quantity = case.proposal.quantity
        seller_id = case.proposal.claimed_seller_id
        seller_verified = None
        payee_id = case.proposal.claimed_payee_id
        latest_snapshot_id = case.latest_snapshot_id
        latest_checkpoint = None
        order_id = case.paypal_order_id
        auth_id = case.paypal_authorization_id
        capture_id = case.paypal_capture_id

    facts = IntentReceiptFacts(
        case_id=case.case_id,
        mandate_id=case.mandate_id,
        mandate_version=case.mandate_version,
        state=case.state,
        product_id=case.proposal.product_id,
        title=title,
        quantity=quantity,
        unit_price=unit_money.to_str(),
        total_amount=total_money.to_str(),
        currency=total_money.currency,
        seller_id=seller_id,
        seller_verified=seller_verified,
        payee_id=payee_id,
        latest_snapshot_id=latest_snapshot_id,
        latest_checkpoint=latest_checkpoint,
        approved_snapshot_id=case.approved_snapshot_id,
        paypal_order_id=order_id,
        paypal_authorization_id=auth_id,
        paypal_capture_id=capture_id,
        latest_ledger_seq=latest_ledger_entry.seq if latest_ledger_entry else None,
        latest_ledger_hash=latest_ledger_entry.hash if latest_ledger_entry else None,
        findings=_summarize_findings(case),
    )
    return facts, total_money, unit_money


def compute_receipt_hash(facts: IntentReceiptFacts) -> str:
    """Compute SHA-256 strictly over canonical JSON of code-verified receipt facts."""
    payload = canonical_json(facts.model_dump(mode="json"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_receipt_hash(receipt: IntentReceipt) -> bool:
    """Verify in constant time that a receipt's SHA-256 hash matches its code-verified facts."""
    expected = compute_receipt_hash(receipt.facts)
    return hmac.compare_digest(expected, receipt.receipt_hash)


def _format_paypal_ref(facts: IntentReceiptFacts) -> str:
    refs: list[str] = []
    if facts.paypal_order_id:
        refs.append(f"order {facts.paypal_order_id}")
    if facts.paypal_authorization_id:
        refs.append(f"auth {facts.paypal_authorization_id}")
    if facts.paypal_capture_id:
        refs.append(f"capture {facts.paypal_capture_id}")
    return f" ({', '.join(refs)})" if refs else ""


def _finding_codes_summary(facts: IntentReceiptFacts) -> str:
    non_info = [f["code"] for f in facts.findings if f.get("severity") != "info"]
    if non_info:
        return ", ".join(non_info)
    return "NONE"


def build_deterministic_receipt_narrative(facts: IntentReceiptFacts) -> str:
    """Render an unambiguous plain-English narrative for every CaseState."""
    pp = _format_paypal_ref(facts)
    reasons = _finding_codes_summary(facts)
    base = (
        f"{facts.total_amount} for '{facts.title}' at payee {facts.payee_id} "
        f"under mandate {facts.mandate_id} v{facts.mandate_version}"
    )

    state = facts.state
    if state == CaseState.VERIFIED:
        return f"Verified {base}{pp}; ProofGuard post-capture checks passed."
    if state == CaseState.CAPTURED:
        return f"Captured {base}{pp}; awaiting ProofGuard post-capture verification."
    if state == CaseState.AUTHORIZED:
        return f"Authorized hold of {base}{pp}; funds not yet captured."
    if state == CaseState.APPROVED:
        return f"Approved {base}; ready for payment authorization."
    if state == CaseState.AWAITING_APPROVAL:
        return f"Awaiting user approval for {base}; pre-approval checks passed."
    if state == CaseState.HELD:
        return f"Held for background recheck on {base}; awaiting resume or approval."
    if state == CaseState.PROPOSED:
        return f"Proposed {base}; awaiting cart lock."
    if state == CaseState.CART_LOCKED:
        return f"Cart locked for {base}; policy recheck in progress."
    if state == CaseState.CHECKED:
        return f"Checked {base}; preparing approval summary."
    if state == CaseState.NEEDS_RECONFIRM:
        return f"Needs reconfirmation for {base}; detected changes/alerts: {reasons}."
    if state == CaseState.BLOCKED:
        return f"Blocked {base}; blocking reasons: {reasons}."
    if state == CaseState.FLAGGED:
        return f"Flagged post-capture {base}{pp}; ProofGuard alerts: {reasons}."
    if state == CaseState.CANCELLED:
        return f"Cancelled {base}{pp}."
    if state == CaseState.EXPIRED:
        return f"Expired {base}; hold or mandate validity window elapsed."
    return f"Case {facts.case_id} ({state.value}) for {base}{pp}."


_MONEY_TOKEN_RE = re.compile(
    r"(?:([$€£₹¥])\s*([0-9][0-9,]*(?:\.[0-9]+)?)|([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Z]{3})\b|\b([A-Z]{3})\s*([0-9][0-9,]*(?:\.[0-9]+)?))"
)

_FORBIDDEN_WORDS_BY_STATE: dict[CaseState, tuple[str, ...]] = {
    CaseState.AWAITING_APPROVAL: ("blocked", "rejected", "denied"),
    CaseState.HELD: ("blocked", "rejected", "denied"),
    CaseState.VERIFIED: ("blocked", "denied", "rejected"),
    CaseState.CAPTURED: ("blocked", "denied", "rejected"),
    CaseState.AUTHORIZED: ("blocked", "denied", "rejected"),
    CaseState.APPROVED: ("blocked", "denied", "rejected"),
    CaseState.PROPOSED: ("blocked",),
    CaseState.CART_LOCKED: ("blocked",),
    CaseState.CHECKED: ("blocked",),
}

_FORBIDDEN_SUCCESS_WORDS_BY_STATE: dict[CaseState, tuple[str, ...]] = {
    CaseState.PROPOSED: ("verified", "captured", "approved"),
    CaseState.CART_LOCKED: ("verified", "captured", "approved"),
    CaseState.CHECKED: ("verified", "captured", "approved"),
    CaseState.AWAITING_APPROVAL: ("verified", "captured"),
    CaseState.HELD: ("verified", "captured"),
    CaseState.BLOCKED: ("verified", "captured", "approved"),
    CaseState.NEEDS_RECONFIRM: ("verified", "captured", "approved"),
    CaseState.FLAGGED: ("verified", "captured", "approved"),
    CaseState.CANCELLED: ("verified", "captured", "approved"),
    CaseState.EXPIRED: ("verified", "captured", "approved"),
}


def _mask_identifiers(text: str, identifiers: tuple[str | None, ...]) -> str:
    masked = text
    for ident in sorted(
        {i.strip() for i in identifiers if isinstance(i, str) and i.strip()},
        key=len,
        reverse=True,
    ):
        masked = re.sub(re.escape(ident), " ", masked, flags=re.IGNORECASE)
    return masked


def has_amount_mismatch_or_status_leak(
    summary: str,
    *,
    expected_amount: Money,
    expected_state: CaseState,
    expected_unit_price: Money | None = None,
    ignored_identifiers: tuple[str | None, ...] = (),
) -> bool:
    """
    Detect unscaled minor-unit leaks (e.g. '2850 USD' for 28.50 USD, '15.00 JPY' for 1500 JPY,
    '12.35 KWD' for 12.345 KWD), currency mismatches, missing authoritative amount/currency,
    or misleading state labels (e.g. calling AWAITING_APPROVAL/HELD 'Blocked', or calling
    FLAGGED/CANCELLED/EXPIRED/NEEDS_RECONFIRM 'Approved'/'Verified'/'Captured').
    """
    text = summary.strip()
    if len(text) < 12 or len(text) > 500:
        return True

    expected_str = str(expected_amount.amount)
    scale = currency_scale(expected_amount.currency)
    if expected_amount.currency not in text:
        return True
    if expected_str not in text.replace(",", ""):
        return True

    masked_for_numbers = _mask_identifiers(text, ignored_identifiers)
    allowed_amounts = {expected_amount.amount}
    if expected_unit_price is not None and expected_unit_price.currency == expected_amount.currency:
        allowed_amounts.add(expected_unit_price.amount)

    for m in _MONEY_TOKEN_RE.finditer(masked_for_numbers):
        num_str = m.group(2) or m.group(3) or m.group(6)
        cur_code = m.group(4) or m.group(5)
        if not num_str:
            continue
        cleaned_num = num_str.replace(",", "")
        try:
            parsed = Decimal(cleaned_num)
        except InvalidOperation:
            return True
        if parsed not in allowed_amounts:
            return True
        if scale == 0 and "." in cleaned_num:
            return True
        if scale > 0:
            exp = parsed.as_tuple().exponent
            if not isinstance(exp, int) or -exp != scale:
                return True
        if cur_code and cur_code != expected_amount.currency:
            return True

    if scale > 0:
        unscaled_int = str(int(expected_amount.amount * (Decimal(10) ** scale)))
        if unscaled_int != expected_str and re.search(
            rf"(?<![A-Za-z0-9_.]){re.escape(unscaled_int)}(?![A-Za-z0-9_.])",
            masked_for_numbers,
        ):
            return True

    lower = re.sub(r"\bseller-[a-z0-9_-]*verified\b", " ", masked_for_numbers.lower())

    for word in _FORBIDDEN_WORDS_BY_STATE.get(expected_state, ()):
        if re.search(rf"\b{word}\b", lower):
            return True

    for word in _FORBIDDEN_SUCCESS_WORDS_BY_STATE.get(expected_state, ()):
        if re.search(rf"(?<!not\s)(?<!never\s)\b{word}\b", lower):
            return True

    return False


async def generate_intent_receipt(
    *,
    case: Case,
    snapshot: CaseSnapshot | None,
    latest_ledger_entry: LedgerEntry | None,
    llm: Any | None = None,
    llm_timeout_seconds: float = 4.0,
) -> IntentReceipt:
    """
    Build a deterministic SHA-256 Intent Receipt strictly from verified domain & ledger state,
    with optional leak-checked LLM plain-English narrative and deterministic template fallback.
    """
    facts, total_money, unit_money = build_receipt_facts(
        case=case,
        snapshot=snapshot,
        latest_ledger_entry=latest_ledger_entry,
    )
    receipt_hash = compute_receipt_hash(facts)
    narrative = build_deterministic_receipt_narrative(facts)
    narrative_source: Literal["deterministic-template", "llm-narrated"] = "deterministic-template"

    summarizer = getattr(llm, "summarize_receipt", None) if llm is not None else None
    if callable(summarizer):
        try:
            candidate = await asyncio.wait_for(
                summarizer(facts=facts.model_dump(mode="json")),
                timeout=llm_timeout_seconds,
            )
            if isinstance(candidate, str) and not has_amount_mismatch_or_status_leak(
                candidate,
                expected_amount=total_money,
                expected_state=facts.state,
                expected_unit_price=unit_money,
                ignored_identifiers=(
                    facts.payee_id,
                    facts.seller_id,
                    facts.case_id,
                    facts.mandate_id,
                    facts.product_id,
                    facts.paypal_order_id,
                    facts.paypal_authorization_id,
                    facts.paypal_capture_id,
                    facts.title,
                ),
            ):
                narrative = candidate.strip()
                narrative_source = "llm-narrated"
        except Exception:
            pass

    return IntentReceipt(
        facts=facts,
        narrative=narrative,
        narrative_source=narrative_source,
        receipt_hash=receipt_hash,
    )
