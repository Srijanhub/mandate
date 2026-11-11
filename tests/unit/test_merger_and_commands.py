from datetime import timedelta

import pytest
from mandate_core.commands import SUPPORTED_COMMANDS, parse_command
from mandate_core.domain.errors import CommandParseError
from mandate_core.domain.models import (
    ConflictCode,
    Mandate,
    MandateStatus,
    Money,
    PaymentEvidence,
    Product,
    Proposal,
    utcnow,
)
from mandate_core.merger import build_snapshot, diff


def test_merger_precedence_and_conflict_codes() -> None:
    mandate = Mandate(
        intent_text="Gift under $60",
        max_total=Money.of("60.00", "USD"),
        expires_at=utcnow() + timedelta(hours=1),
        status=MandateStatus.ACTIVE,
    )
    proposal = Proposal(
        mandate_id=mandate.mandate_id,
        product_id="p1",
        title="Candle",
        quantity=1,
        claimed_unit_price=Money.of("28.50", "USD"),
        claimed_total=Money.of("28.50", "USD"),
        claimed_seller_id="seller-a",
        claimed_payee_id="SELLER-A",
    )
    drifted_catalog = Product(
        product_id="p1",
        title="Candle",
        price=Money.of("49.00", "USD"),
        seller_id="seller-a",
        seller_name="Seller A",
        seller_verified=True,
        payee_id="SELLER-A",
        category="gifts",
        in_stock=True,
    )
    wrong_paypal = PaymentEvidence(
        order_id="ORD-1",
        status="AUTHORIZED",
        amount=Money.of("49.00", "USD"),
        payee_id="SELLER-B-ATTACKER",
    )

    snap, findings = build_snapshot(
        case_id="case-1",
        checkpoint="C5",
        mandate=mandate,
        proposal=proposal,
        catalog_item=drifted_catalog,
        payment_evidence=wrong_paypal,
    )
    codes = {f.code for f in findings}
    assert ConflictCode.PRICE_DRIFT.value in codes
    assert ConflictCode.PAYEE_MISMATCH.value in codes
    assert snap.unit_price == Money.of("49.00", "USD")
    assert snap.payee_id == "SELLER-B-ATTACKER"

    # Diff between initial clean snapshot and drifted snapshot
    clean_snap, _ = build_snapshot(
        case_id="case-1",
        checkpoint="C3",
        mandate=mandate,
        proposal=proposal,
        catalog_item=drifted_catalog.model_copy(update={"price": Money.of("28.50", "USD")}),
    )
    drift_list = diff(clean_snap, snap)
    assert {f.code for f in drift_list} >= {
        ConflictCode.PRICE_DRIFT.value,
        ConflictCode.PAYEE_MISMATCH.value,
    }


def test_command_parser_enforces_control_plane_vs_data_plane_boundary() -> None:
    # Untrusted data sources must NEVER execute commands
    for untrusted in ("product_text", "agent_output", "catalog_description", "webhook"):
        with pytest.raises(CommandParseError) as exc_info:
            parse_command("/approve", source=untrusted)
        assert exc_info.value.code == "UNTRUSTED_CONTROL_PLANE_SOURCE"

    # Natural language is intent-only (returns None)
    assert parse_command("buy my girlfriend a gift under $60", source="user_command") is None

    # All supported commands parse deterministically pre-LLM
    for cmd in SUPPORTED_COMMANDS:
        parsed = parse_command(f"/{cmd} arg1", source="user_command")
        assert parsed is not None
        assert parsed.name == cmd
