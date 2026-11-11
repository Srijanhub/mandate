from __future__ import annotations

from datetime import timedelta

from mandate_core.domain.models import (
    CaseSnapshot,
    ConflictCode,
    Finding,
    FindingSeverity,
    Mandate,
    PaymentEvidence,
    Product,
    Proposal,
    utcnow,
)

EXPLANATION_TEMPLATES: dict[str, str] = {
    ConflictCode.PRICE_DRIFT.value: (
        "Blocked: catalog price drifted after the option was proposed or approved "
        "({before} -> {after})."
    ),
    ConflictCode.PAYEE_MISMATCH.value: (
        "Blocked: payment payee changed mid-checkout from expected '{expected}' to '{actual}'."
    ),
    ConflictCode.CURRENCY_MISMATCH.value: (
        "Blocked: currency mismatch detected ({expected} vs {actual})."
    ),
    ConflictCode.QTY_MISMATCH.value: (
        "Blocked: quantity or line-item total arithmetic failed verification ({detail})."
    ),
    ConflictCode.SELLER_CHANGED.value: (
        "Blocked: authoritative catalog seller changed from '{expected}' to '{actual}'."
    ),
    ConflictCode.OUT_OF_STOCK.value: (
        "Blocked: product '{product_id}' is out of stock or no longer available."
    ),
    ConflictCode.AMOUNT_MISMATCH.value: (
        "Blocked: payment evidence amount ({actual}) does not match authoritative order total ({expected})."
    ),
}


def explain_finding_code(code: str, **kwargs: object) -> str:
    template = EXPLANATION_TEMPLATES.get(code)
    if template is None:
        return str(kwargs.get("fallback", f"Policy finding triggered: {code}"))
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


def build_snapshot(
    *,
    case_id: str,
    checkpoint: str,
    mandate: Mandate,
    proposal: Proposal,
    catalog_item: Product | None = None,
    payment_evidence: PaymentEvidence | None = None,
) -> tuple[CaseSnapshot, list[Finding]]:
    """
    Build one canonical CaseSnapshot from 4 sources using strict precedence:
      Facts precedence: PayPal evidence > fresh catalog fetch > agent claim.
      Rules precedence: Mandate always wins.
    Pure function; detects and emits conflict findings whenever sources disagree.
    """
    findings: list[Finding] = []
    sources_used = ["mandate", "proposal"]

    # Check agent proposal self-consistency first
    expected_claim_total = proposal.claimed_unit_price * proposal.quantity
    if proposal.claimed_total.currency != proposal.claimed_unit_price.currency:
        findings.append(
            Finding(
                code=ConflictCode.CURRENCY_MISMATCH.value,
                severity=FindingSeverity.BLOCK,
                source="merger",
                message="Proposal unit price and total currencies disagree",
                explanation=explain_finding_code(
                    ConflictCode.CURRENCY_MISMATCH.value,
                    expected=proposal.claimed_unit_price.currency,
                    actual=proposal.claimed_total.currency,
                ),
            )
        )
    elif proposal.claimed_total != expected_claim_total:
        findings.append(
            Finding(
                code=ConflictCode.QTY_MISMATCH.value,
                severity=FindingSeverity.BLOCK,
                source="merger",
                message="Proposal claimed_total != claimed_unit_price * quantity",
                explanation=explain_finding_code(
                    ConflictCode.QTY_MISMATCH.value,
                    detail=f"{proposal.claimed_unit_price.to_str()} x {proposal.quantity} != {proposal.claimed_total.to_str()}",
                ),
            )
        )

    # Catalog truth (higher precedence than agent proposal)
    if catalog_item is None:
        findings.append(
            Finding(
                code=ConflictCode.OUT_OF_STOCK.value,
                severity=FindingSeverity.BLOCK,
                source="merger",
                message=f"Catalog item '{proposal.product_id}' missing",
                explanation=explain_finding_code(
                    ConflictCode.OUT_OF_STOCK.value, product_id=proposal.product_id
                ),
            )
        )
        unit_price = proposal.claimed_unit_price
        total_amount = expected_claim_total
        seller_id = proposal.claimed_seller_id
        seller_name = proposal.claimed_seller_id
        seller_verified = False
        payee_id = proposal.claimed_payee_id
        in_stock = False
        category = proposal.category or "unknown"
        title = proposal.title
        estimated_delivery_at = proposal.estimated_delivery_at
    else:
        sources_used.append("catalog")
        if not catalog_item.in_stock:
            findings.append(
                Finding(
                    code=ConflictCode.OUT_OF_STOCK.value,
                    severity=FindingSeverity.BLOCK,
                    source="merger",
                    message=f"Catalog item '{catalog_item.product_id}' out of stock",
                    explanation=explain_finding_code(
                        ConflictCode.OUT_OF_STOCK.value, product_id=catalog_item.product_id
                    ),
                )
            )

        if catalog_item.price.currency != proposal.claimed_unit_price.currency:
            findings.append(
                Finding(
                    code=ConflictCode.CURRENCY_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="merger",
                    message="Catalog currency differs from agent proposal",
                    explanation=explain_finding_code(
                        ConflictCode.CURRENCY_MISMATCH.value,
                        expected=catalog_item.price.currency,
                        actual=proposal.claimed_unit_price.currency,
                    ),
                )
            )
        elif catalog_item.price != proposal.claimed_unit_price:
            findings.append(
                Finding(
                    code=ConflictCode.PRICE_DRIFT.value,
                    severity=FindingSeverity.BLOCK,
                    source="merger",
                    message=(
                        f"Catalog unit price {catalog_item.price.to_str()} != "
                        f"agent claimed {proposal.claimed_unit_price.to_str()}"
                    ),
                    explanation=explain_finding_code(
                        ConflictCode.PRICE_DRIFT.value,
                        before=proposal.claimed_unit_price.to_str(),
                        after=catalog_item.price.to_str(),
                    ),
                    evidence={
                        "claimed": str(proposal.claimed_unit_price.amount),
                        "catalog": str(catalog_item.price.amount),
                        "currency": catalog_item.price.currency,
                    },
                )
            )

        if catalog_item.seller_id != proposal.claimed_seller_id:
            findings.append(
                Finding(
                    code=ConflictCode.SELLER_CHANGED.value,
                    severity=FindingSeverity.BLOCK,
                    source="merger",
                    message=(
                        f"Catalog seller {catalog_item.seller_id} != "
                        f"agent claimed {proposal.claimed_seller_id}"
                    ),
                    explanation=explain_finding_code(
                        ConflictCode.SELLER_CHANGED.value,
                        expected=proposal.claimed_seller_id,
                        actual=catalog_item.seller_id,
                    ),
                )
            )

        if catalog_item.payee_id != proposal.claimed_payee_id:
            findings.append(
                Finding(
                    code=ConflictCode.PAYEE_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="merger",
                    message=(
                        f"Catalog payee {catalog_item.payee_id} != "
                        f"agent claimed {proposal.claimed_payee_id}"
                    ),
                    explanation=explain_finding_code(
                        ConflictCode.PAYEE_MISMATCH.value,
                        expected=catalog_item.payee_id,
                        actual=proposal.claimed_payee_id,
                    ),
                )
            )

        unit_price = catalog_item.price
        total_amount = catalog_item.price * proposal.quantity
        seller_id = catalog_item.seller_id
        seller_name = catalog_item.seller_name
        seller_verified = catalog_item.seller_verified
        payee_id = catalog_item.payee_id
        in_stock = catalog_item.in_stock
        category = catalog_item.category
        title = catalog_item.title
        estimated_delivery_at = proposal.estimated_delivery_at or (
            utcnow() + timedelta(days=catalog_item.estimated_delivery_days)
        )

    # PayPal payment evidence (highest precedence for money & payee)
    paypal_order_id = None
    paypal_authorization_id = None
    paypal_capture_id = None

    if payment_evidence is not None:
        sources_used.append("paypal")
        paypal_order_id = payment_evidence.order_id
        paypal_authorization_id = payment_evidence.authorization_id
        paypal_capture_id = payment_evidence.capture_id

        if payment_evidence.amount.currency != total_amount.currency:
            findings.append(
                Finding(
                    code=ConflictCode.CURRENCY_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="merger",
                    message="PayPal currency differs from authoritative snapshot currency",
                    explanation=explain_finding_code(
                        ConflictCode.CURRENCY_MISMATCH.value,
                        expected=total_amount.currency,
                        actual=payment_evidence.amount.currency,
                    ),
                )
            )
        elif payment_evidence.amount != total_amount:
            findings.append(
                Finding(
                    code=ConflictCode.AMOUNT_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="merger",
                    message=(
                        f"PayPal amount {payment_evidence.amount.to_str()} != "
                        f"authoritative total {total_amount.to_str()}"
                    ),
                    explanation=explain_finding_code(
                        ConflictCode.AMOUNT_MISMATCH.value,
                        expected=total_amount.to_str(),
                        actual=payment_evidence.amount.to_str(),
                    ),
                    evidence={
                        "expected_total": str(total_amount.amount),
                        "paypal_amount": str(payment_evidence.amount.amount),
                    },
                )
            )

        if payment_evidence.payee_id and payment_evidence.payee_id != payee_id:
            findings.append(
                Finding(
                    code=ConflictCode.PAYEE_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="merger",
                    message=(
                        f"PayPal payee {payment_evidence.payee_id} != "
                        f"expected payee {payee_id}"
                    ),
                    explanation=explain_finding_code(
                        ConflictCode.PAYEE_MISMATCH.value,
                        expected=payee_id,
                        actual=payment_evidence.payee_id,
                    ),
                    evidence={"expected_payee": payee_id, "paypal_payee": payment_evidence.payee_id},
                )
            )
            payee_id = payment_evidence.payee_id

        # PayPal evidence wins for factual total_amount once recorded
        total_amount = payment_evidence.amount

    snapshot = CaseSnapshot(
        case_id=case_id,
        checkpoint=checkpoint,
        mandate_id=mandate.mandate_id,
        mandate_version=mandate.version,
        product_id=proposal.product_id,
        title=title,
        quantity=proposal.quantity,
        unit_price=unit_price,
        total_amount=total_amount,
        seller_id=seller_id,
        seller_name=seller_name,
        seller_verified=seller_verified,
        payee_id=payee_id,
        in_stock=in_stock,
        category=category,
        estimated_delivery_at=estimated_delivery_at,
        paypal_order_id=paypal_order_id,
        paypal_authorization_id=paypal_authorization_id,
        paypal_capture_id=paypal_capture_id,
        sources_used=sources_used,
    )
    return snapshot, findings


def diff(snapshot_a: CaseSnapshot, snapshot_b: CaseSnapshot) -> list[Finding]:
    """Compare two snapshots (e.g. approved vs fresh recheck) and emit conflict findings."""
    findings: list[Finding] = []

    if snapshot_a.total_amount.currency != snapshot_b.total_amount.currency:
        findings.append(
            Finding(
                code=ConflictCode.CURRENCY_MISMATCH.value,
                severity=FindingSeverity.BLOCK,
                source="drift_diff",
                message=(
                    f"Currency changed {snapshot_a.total_amount.currency} -> "
                    f"{snapshot_b.total_amount.currency}"
                ),
                explanation=explain_finding_code(
                    ConflictCode.CURRENCY_MISMATCH.value,
                    expected=snapshot_a.total_amount.currency,
                    actual=snapshot_b.total_amount.currency,
                ),
            )
        )
    else:
        if snapshot_a.unit_price != snapshot_b.unit_price:
            findings.append(
                Finding(
                    code=ConflictCode.PRICE_DRIFT.value,
                    severity=FindingSeverity.BLOCK,
                    source="drift_diff",
                    message=f"Unit price drifted {snapshot_a.unit_price.to_str()} -> {snapshot_b.unit_price.to_str()}",
                    explanation=explain_finding_code(
                        ConflictCode.PRICE_DRIFT.value,
                        before=snapshot_a.unit_price.to_str(),
                        after=snapshot_b.unit_price.to_str(),
                    ),
                    evidence={
                        "before": str(snapshot_a.unit_price.amount),
                        "after": str(snapshot_b.unit_price.amount),
                        "currency": snapshot_b.unit_price.currency,
                    },
                )
            )
        if snapshot_a.total_amount != snapshot_b.total_amount:
            findings.append(
                Finding(
                    code=ConflictCode.AMOUNT_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="drift_diff",
                    message=(
                        f"Total drifted {snapshot_a.total_amount.to_str()} -> "
                        f"{snapshot_b.total_amount.to_str()}"
                    ),
                    explanation=explain_finding_code(
                        ConflictCode.AMOUNT_MISMATCH.value,
                        expected=snapshot_a.total_amount.to_str(),
                        actual=snapshot_b.total_amount.to_str(),
                    ),
                )
            )

    if snapshot_a.quantity != snapshot_b.quantity:
        findings.append(
            Finding(
                code=ConflictCode.QTY_MISMATCH.value,
                severity=FindingSeverity.BLOCK,
                source="drift_diff",
                message=f"Quantity changed {snapshot_a.quantity} -> {snapshot_b.quantity}",
                explanation=explain_finding_code(
                    ConflictCode.QTY_MISMATCH.value,
                    detail=f"quantity changed {snapshot_a.quantity} -> {snapshot_b.quantity}",
                ),
            )
        )

    if snapshot_a.seller_id != snapshot_b.seller_id:
        findings.append(
            Finding(
                code=ConflictCode.SELLER_CHANGED.value,
                severity=FindingSeverity.BLOCK,
                source="drift_diff",
                message=f"Seller changed {snapshot_a.seller_id} -> {snapshot_b.seller_id}",
                explanation=explain_finding_code(
                    ConflictCode.SELLER_CHANGED.value,
                    expected=snapshot_a.seller_id,
                    actual=snapshot_b.seller_id,
                ),
            )
        )

    if snapshot_a.payee_id != snapshot_b.payee_id:
        findings.append(
            Finding(
                code=ConflictCode.PAYEE_MISMATCH.value,
                severity=FindingSeverity.BLOCK,
                source="drift_diff",
                message=f"Payee changed {snapshot_a.payee_id} -> {snapshot_b.payee_id}",
                explanation=explain_finding_code(
                    ConflictCode.PAYEE_MISMATCH.value,
                    expected=snapshot_a.payee_id,
                    actual=snapshot_b.payee_id,
                ),
            )
        )

    if snapshot_a.in_stock and not snapshot_b.in_stock:
        findings.append(
            Finding(
                code=ConflictCode.OUT_OF_STOCK.value,
                severity=FindingSeverity.BLOCK,
                source="drift_diff",
                message=f"Product '{snapshot_b.product_id}' went out of stock",
                explanation=explain_finding_code(
                    ConflictCode.OUT_OF_STOCK.value, product_id=snapshot_b.product_id
                ),
            )
        )

    return findings
