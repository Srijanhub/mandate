from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from mandate_core.domain.models import (
    CaseSnapshot,
    EmailProposal,
    FindingSeverity,
    Mandate,
    MandateStatus,
    Money,
    utcnow,
)
from mandate_core.rules import RuleContext, evaluate_rules, load_policy_pack


def test_money_uses_decimal_and_rejects_floats() -> None:
    m1 = Money.of("19.99", "usd")
    m2 = Money.of("0.01", "USD")
    assert (m1 + m2) == Money.of("20.00", "USD")
    assert m1.currency == "USD"

    with pytest.raises(TypeError):
        Money(amount=19.99, currency="USD")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money.of(True, "USD")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Money.of("10.999", "USD")
    with pytest.raises(ValueError):
        Money.of("-1.00", "USD")
    with pytest.raises(ValueError):
        _ = m1 + Money.of("1.00", "EUR")


@given(
    cap_cents=st.integers(min_value=1, max_value=50_000),
    price_cents=st.integers(min_value=1, max_value=100_000),
    qty=st.integers(min_value=1, max_value=5),
)
def test_hypothesis_any_total_above_mandate_limit_always_blocks(
    cap_cents: int, price_cents: int, qty: int
) -> None:
    cap = Money.of(Decimal(cap_cents) / Decimal(100), "USD")
    unit_price = Money.of(Decimal(price_cents) / Decimal(100), "USD")
    total = unit_price * qty

    now = utcnow()
    mandate = Mandate(
        intent_text="Property test",
        max_total=cap,
        expires_at=now + timedelta(hours=1),
        status=MandateStatus.ACTIVE,
        require_verified_seller=True,
    )
    snap = CaseSnapshot(
        case_id="c1",
        checkpoint="C1",
        mandate_id=mandate.mandate_id,
        mandate_version=1,
        product_id="p1",
        title="Item",
        quantity=qty,
        unit_price=unit_price,
        total_amount=total,
        seller_id="seller-a",
        seller_name="Seller A",
        seller_verified=True,
        payee_id="SELLER-A",
        in_stock=True,
        category="gifts",
    )
    decision = evaluate_rules(RuleContext(mandate=mandate, snapshot=snap, now=now))
    if total > cap:
        assert decision.allow is False
        assert decision.verdict == "BLOCK"
        assert any(f.code == "EXCEEDS_MAX_TOTAL" for f in decision.findings)
    else:
        assert decision.allow is True


def test_rules_run_all_without_short_circuiting_and_enforce_velocity() -> None:
    now = utcnow()
    mandate = Mandate(
        intent_text="Velocity & seller test",
        max_total=Money.of("60.00", "USD"),
        max_spend_per_day=Money.of("100.00", "USD"),
        max_spend_per_week=Money.of("200.00", "USD"),
        spent_today=Money.of("70.00", "USD"),
        spent_this_week=Money.of("170.00", "USD"),
        deliver_by=now + timedelta(days=1),
        expires_at=now + timedelta(hours=2),
        allowed_categories=["gifts"],
        blocked_keywords=["gift card"],
        status=MandateStatus.ACTIVE,
    )
    snap = CaseSnapshot(
        case_id="c2",
        checkpoint="C2",
        mandate_id=mandate.mandate_id,
        mandate_version=1,
        product_id="p2",
        title="Prepaid Gift Card",
        quantity=1,
        unit_price=Money.of("45.00", "USD"),
        total_amount=Money.of("45.00", "USD"),
        seller_id="seller-b",
        seller_name="Seller B",
        seller_verified=False,
        payee_id="SELLER-B",
        in_stock=False,
        category="gift_cards",
        estimated_delivery_at=now + timedelta(days=5),
    )

    decision = evaluate_rules(RuleContext(mandate=mandate, snapshot=snap, now=now))
    assert decision.allow is False
    block_codes = {f.code for f in decision.findings if f.severity == FindingSeverity.BLOCK}
    assert {
        "DAILY_VELOCITY_EXCEEDED",
        "UNVERIFIED_SELLER",
        "DELIVERY_TOO_LATE",
        "BLOCKED_KEYWORD",
        "OUT_OF_STOCK",
    } <= block_codes


def test_second_domain_email_policy_pack_reuses_same_rule_engine() -> None:
    pack = load_policy_pack("email")
    assert "max_recipients" in pack["rules"]
    assert "allowlist_domain" in pack["rules"]

    now = utcnow()
    mandate = Mandate(
        domain="email",
        intent_text="Company email only, max 2 recipients",
        max_total=Money.zero("USD"),
        max_recipients=2,
        allowed_recipient_domains=["company.com"],
        expires_at=now + timedelta(hours=1),
        status=MandateStatus.ACTIVE,
    )
    ok_email = EmailProposal(
        mandate_id=mandate.mandate_id,
        subject="Status",
        recipients=["alice@company.com", "bob@company.com"],
    )
    bad_email = EmailProposal(
        mandate_id=mandate.mandate_id,
        subject="Leak",
        recipients=["a@company.com", "b@company.com", "evil@attacker.io"],
    )

    assert evaluate_rules(RuleContext(mandate=mandate, email_proposal=ok_email, now=now)).allow is True
    bad_dec = evaluate_rules(RuleContext(mandate=mandate, email_proposal=bad_email, now=now))
    assert bad_dec.allow is False
    codes = {f.code for f in bad_dec.findings if f.severity == FindingSeverity.BLOCK}
    assert codes == {"TOO_MANY_RECIPIENTS", "RECIPIENT_DOMAIN_BLOCKED"}
