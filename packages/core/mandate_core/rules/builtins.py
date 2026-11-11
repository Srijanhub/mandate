from __future__ import annotations

from mandate_core.domain.models import Finding, FindingSeverity, MandateStatus, Money
from mandate_core.rules.registry import RuleContext, register_rule


def _pass(rule: str, message: str, evidence: dict[str, object] | None = None) -> Finding:
    return Finding(
        code=f"RULE_{rule.upper()}_OK",
        severity=FindingSeverity.INFO,
        source=f"rule:{rule}",
        message=message,
        explanation=message,
        evidence=evidence or {},
    )


def _block(
    rule: str, code: str, message: str, explanation: str, evidence: dict[str, object] | None = None
) -> Finding:
    return Finding(
        code=code,
        severity=FindingSeverity.BLOCK,
        source=f"rule:{rule}",
        message=message,
        explanation=explanation,
        evidence=evidence or {},
    )


# ---------------------------------------------------------------------------
# Shopping Domain Rules
# ---------------------------------------------------------------------------


@register_rule("mandate_active", domain="shopping")
def rule_shopping_mandate_active(ctx: RuleContext) -> Finding:
    if ctx.mandate.status != MandateStatus.ACTIVE:
        return _block(
            "mandate_active",
            f"MANDATE_{ctx.mandate.status.value}",
            f"Mandate status is {ctx.mandate.status.value}",
            f"Blocked: mandate is {ctx.mandate.status.value} and must be ACTIVE before spending.",
            {"status": ctx.mandate.status.value},
        )
    return _pass("mandate_active", "Mandate is ACTIVE.")


@register_rule("expires_at", domain="shopping")
def rule_shopping_expires_at(ctx: RuleContext) -> Finding:
    now = ctx.current_time
    if now > ctx.mandate.expires_at:
        return _block(
            "expires_at",
            "MANDATE_EXPIRED",
            f"Mandate expired at {ctx.mandate.expires_at.isoformat()}",
            f"Blocked: mandate expired on {ctx.mandate.expires_at.isoformat()}.",
            {"now": now.isoformat(), "expires_at": ctx.mandate.expires_at.isoformat()},
        )
    return _pass("expires_at", f"Mandate valid until {ctx.mandate.expires_at.isoformat()}.")


@register_rule("max_total", domain="shopping")
def rule_max_total(ctx: RuleContext) -> Finding:
    snap = ctx.snapshot
    if snap is None:
        return _block(
            "max_total",
            "SNAPSHOT_MISSING",
            "Missing case snapshot",
            "Blocked: no verified case snapshot available to verify total.",
        )
    if snap.total_amount.currency != ctx.mandate.max_total.currency:
        return _block(
            "max_total",
            "CURRENCY_MISMATCH",
            f"Currency {snap.total_amount.currency} != {ctx.mandate.max_total.currency}",
            (
                f"Blocked: order currency {snap.total_amount.currency} does not match "
                f"mandate currency {ctx.mandate.max_total.currency}."
            ),
            {
                "order_currency": snap.total_amount.currency,
                "mandate_currency": ctx.mandate.max_total.currency,
            },
        )
    if snap.total_amount > ctx.mandate.max_total:
        return _block(
            "max_total",
            "EXCEEDS_MAX_TOTAL",
            f"Order total {snap.total_amount.to_str()} > max_total {ctx.mandate.max_total.to_str()}",
            (
                f"Blocked: order total {snap.total_amount.to_str()} exceeds your "
                f"{ctx.mandate.max_total.to_str()} limit."
            ),
            {
                "total": str(snap.total_amount.amount),
                "max_total": str(ctx.mandate.max_total.amount),
                "currency": snap.total_amount.currency,
            },
        )
    return _pass(
        "max_total",
        f"Total {snap.total_amount.to_str()} is within {ctx.mandate.max_total.to_str()} cap.",
    )


@register_rule("max_spend_per_day", domain="shopping")
def rule_max_spend_per_day(ctx: RuleContext) -> Finding:
    snap = ctx.snapshot
    limit = ctx.mandate.max_spend_per_day
    if limit is None or snap is None:
        return _pass("max_spend_per_day", "No daily spend velocity limit configured.")
    spent_today = ctx.mandate.spent_today or Money.zero(limit.currency)
    if snap.total_amount.currency != limit.currency:
        return _block(
            "max_spend_per_day",
            "CURRENCY_MISMATCH",
            "Daily velocity currency mismatch",
            f"Blocked: currency {snap.total_amount.currency} != daily cap currency {limit.currency}.",
        )
    projected = spent_today + snap.total_amount
    if projected > limit:
        return _block(
            "max_spend_per_day",
            "DAILY_VELOCITY_EXCEEDED",
            f"Projected daily spend {projected.to_str()} > {limit.to_str()}",
            f"Blocked: projected daily spend {projected.to_str()} exceeds daily limit {limit.to_str()}.",
            {"spent_today": str(spent_today.amount), "projected": str(projected.amount), "limit": str(limit.amount)},
        )
    return _pass("max_spend_per_day", f"Projected daily spend {projected.to_str()} <= {limit.to_str()}.")


@register_rule("max_spend_per_week", domain="shopping")
def rule_max_spend_per_week(ctx: RuleContext) -> Finding:
    snap = ctx.snapshot
    limit = ctx.mandate.max_spend_per_week
    if limit is None or snap is None:
        return _pass("max_spend_per_week", "No weekly spend velocity limit configured.")
    spent_week = ctx.mandate.spent_this_week or Money.zero(limit.currency)
    if snap.total_amount.currency != limit.currency:
        return _block(
            "max_spend_per_week",
            "CURRENCY_MISMATCH",
            "Weekly velocity currency mismatch",
            f"Blocked: currency {snap.total_amount.currency} != weekly cap currency {limit.currency}.",
        )
    projected = spent_week + snap.total_amount
    if projected > limit:
        return _block(
            "max_spend_per_week",
            "WEEKLY_VELOCITY_EXCEEDED",
            f"Projected weekly spend {projected.to_str()} > {limit.to_str()}",
            f"Blocked: projected weekly spend {projected.to_str()} exceeds weekly limit {limit.to_str()}.",
            {"spent_week": str(spent_week.amount), "projected": str(projected.amount), "limit": str(limit.amount)},
        )
    return _pass("max_spend_per_week", f"Projected weekly spend {projected.to_str()} <= {limit.to_str()}.")


@register_rule("max_transactions", domain="shopping")
def rule_max_transactions(ctx: RuleContext) -> Finding:
    if ctx.mandate.tx_count >= ctx.mandate.max_transactions:
        return _block(
            "max_transactions",
            "MAX_TRANSACTIONS_EXCEEDED",
            f"Transactions {ctx.mandate.tx_count} >= {ctx.mandate.max_transactions}",
            f"Blocked: mandate transaction limit ({ctx.mandate.max_transactions}) reached.",
            {"tx_count": ctx.mandate.tx_count, "max_transactions": ctx.mandate.max_transactions},
        )
    return _pass(
        "max_transactions",
        f"Transaction count {ctx.mandate.tx_count + 1}/{ctx.mandate.max_transactions}.",
    )


@register_rule("seller_policy", domain="shopping")
def rule_seller_policy(ctx: RuleContext) -> Finding:
    snap = ctx.snapshot
    if snap is None:
        return _block(
            "seller_policy",
            "SNAPSHOT_MISSING",
            "Missing snapshot",
            "Blocked: no snapshot available to verify seller.",
        )

    blocked = {s.strip().lower() for s in ctx.mandate.blocked_sellers if s.strip()}
    tokens = {snap.seller_id.strip().lower(), snap.payee_id.strip().lower()}
    if tokens & blocked:
        return _block(
            "seller_policy",
            "SELLER_BLOCKED",
            f"Seller {snap.seller_id} is blocked",
            f"Blocked: seller '{snap.seller_name}' ({snap.seller_id}) is on your blocklist.",
            {"seller_id": snap.seller_id, "payee_id": snap.payee_id},
        )

    if ctx.mandate.require_verified_seller and not snap.seller_verified:
        return _block(
            "seller_policy",
            "UNVERIFIED_SELLER",
            f"Seller {snap.seller_id} is not verified",
            f"Blocked: seller '{snap.seller_name}' ({snap.seller_id}) is not verified, and verified sellers only is required.",
            {"seller_id": snap.seller_id, "seller_verified": snap.seller_verified},
        )

    allowed = {s.strip().lower() for s in ctx.mandate.allowed_sellers if s.strip()}
    if allowed and not (tokens & allowed):
        return _block(
            "seller_policy",
            "SELLER_NOT_ALLOWED",
            f"Seller {snap.seller_id} / payee {snap.payee_id} not in allowed list",
            f"Blocked: seller '{snap.seller_name}' ({snap.payee_id}) is not in your allowed sellers list.",
            {"seller_id": snap.seller_id, "payee_id": snap.payee_id, "allowed_sellers": ctx.mandate.allowed_sellers},
        )

    return _pass("seller_policy", f"Seller '{snap.seller_name}' ({snap.payee_id}) passed seller policy.")


@register_rule("deliver_by", domain="shopping")
def rule_deliver_by(ctx: RuleContext) -> Finding:
    snap = ctx.snapshot
    deadline = ctx.mandate.deliver_by
    if deadline is None or snap is None:
        return _pass("deliver_by", "No delivery deadline set.")
    if snap.estimated_delivery_at is None:
        return _block(
            "deliver_by",
            "DELIVERY_DATE_MISSING",
            "Estimated delivery date missing",
            f"Blocked: item lacks an estimated delivery date to confirm arrival by {deadline.isoformat()}.",
        )
    if snap.estimated_delivery_at > deadline:
        return _block(
            "deliver_by",
            "DELIVERY_TOO_LATE",
            f"Delivery {snap.estimated_delivery_at.isoformat()} > {deadline.isoformat()}",
            (
                f"Blocked: estimated delivery ({snap.estimated_delivery_at.date().isoformat()}) "
                f"misses your deadline ({deadline.date().isoformat()})."
            ),
            {
                "estimated_delivery_at": snap.estimated_delivery_at.isoformat(),
                "deliver_by": deadline.isoformat(),
            },
        )
    return _pass("deliver_by", f"Estimated delivery {snap.estimated_delivery_at.date().isoformat()} meets deadline.")


@register_rule("category_policy", domain="shopping")
def rule_category_policy(ctx: RuleContext) -> Finding:
    snap = ctx.snapshot
    if snap is None:
        return _pass("category_policy", "No snapshot.")

    title_lower = snap.title.lower()
    for kw in ctx.mandate.blocked_keywords:
        kw_clean = kw.strip().lower()
        if kw_clean and kw_clean in title_lower:
            return _block(
                "category_policy",
                "BLOCKED_KEYWORD",
                f"Blocked keyword '{kw_clean}' matched '{snap.title}'",
                f"Blocked: product '{snap.title}' contains prohibited keyword '{kw_clean}'.",
                {"keyword": kw_clean, "title": snap.title},
            )

    allowed_cats = {c.strip().lower() for c in ctx.mandate.allowed_categories if c.strip()}
    if allowed_cats and snap.category.strip().lower() not in allowed_cats:
        return _block(
            "category_policy",
            "CATEGORY_NOT_ALLOWED",
            f"Category '{snap.category}' not in {sorted(allowed_cats)}",
            f"Blocked: category '{snap.category}' is outside your allowed categories.",
            {"category": snap.category, "allowed_categories": sorted(allowed_cats)},
        )

    return _pass("category_policy", f"Category '{snap.category}' and keywords passed.")


@register_rule("stock_availability", domain="shopping")
def rule_stock_availability(ctx: RuleContext) -> Finding:
    snap = ctx.snapshot
    if snap is None:
        return _pass("stock_availability", "No snapshot.")
    if not snap.in_stock:
        return _block(
            "stock_availability",
            "OUT_OF_STOCK",
            f"Product {snap.product_id} is out of stock",
            f"Blocked: '{snap.title}' is currently out of stock.",
            {"product_id": snap.product_id},
        )
    return _pass("stock_availability", "Product is in stock.")


# ---------------------------------------------------------------------------
# Second Domain Pack: Email-Sending Agent (proves Mandate Core reusability!)
# ---------------------------------------------------------------------------


@register_rule("mandate_active", domain="email")
def rule_email_mandate_active(ctx: RuleContext) -> Finding:
    return rule_shopping_mandate_active(ctx)


@register_rule("expires_at", domain="email")
def rule_email_expires_at(ctx: RuleContext) -> Finding:
    return rule_shopping_expires_at(ctx)


@register_rule("max_recipients", domain="email")
def rule_email_max_recipients(ctx: RuleContext) -> Finding:
    prop = ctx.email_proposal
    if prop is None:
        return _block("max_recipients", "EMAIL_PROPOSAL_MISSING", "Missing email proposal", "Blocked: no email proposal.")
    if not prop.recipients:
        return _block("max_recipients", "NO_RECIPIENTS", "Empty recipients", "Blocked: email has zero recipients.")
    cap = ctx.mandate.max_recipients
    if cap is not None and len(prop.recipients) > cap:
        return _block(
            "max_recipients",
            "TOO_MANY_RECIPIENTS",
            f"{len(prop.recipients)} recipients > max_recipients {cap}",
            f"Blocked: email targets {len(prop.recipients)} recipients, exceeding limit of {cap}.",
            {"count": len(prop.recipients), "max_recipients": cap},
        )
    return _pass("max_recipients", f"Recipient count ({len(prop.recipients)}) is within limit.")


@register_rule("allowlist_domain", domain="email")
def rule_email_allowlist_domain(ctx: RuleContext) -> Finding:
    prop = ctx.email_proposal
    if prop is None:
        return _block("allowlist_domain", "EMAIL_PROPOSAL_MISSING", "Missing email proposal", "Blocked: no email proposal.")
    allowed = {d.strip().lower() for d in ctx.mandate.allowed_recipient_domains if d.strip()}
    if not allowed:
        return _pass("allowlist_domain", "No recipient domain restriction set.")
    disallowed: list[str] = []
    for addr in prop.recipients:
        if "@" not in addr:
            disallowed.append(addr)
            continue
        domain = addr.rsplit("@", 1)[1].strip().lower()
        if domain not in allowed:
            disallowed.append(addr)
    if disallowed:
        return _block(
            "allowlist_domain",
            "RECIPIENT_DOMAIN_BLOCKED",
            f"Disallowed recipient(s): {', '.join(disallowed)}",
            f"Blocked: recipient(s) {', '.join(disallowed)} are outside allowed domains {sorted(allowed)}.",
            {"disallowed": disallowed, "allowed_domains": sorted(allowed)},
        )
    return _pass("allowlist_domain", f"All recipient domains match allowlist {sorted(allowed)}.")
