from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from mandate_core.domain.models import (
    Case,
    CaseSnapshot,
    CaseState,
    Finding,
    FindingSeverity,
    LedgerEntry,
    Money,
    Proposal,
    utcnow,
)
from mandate_core.ledger import (
    GENESIS_HASH,
    build_deterministic_receipt_narrative,
    build_receipt_facts,
    canonical_json,
    compute_entry_hash,
    compute_receipt_hash,
    generate_intent_receipt,
    has_amount_mismatch_or_status_leak,
)

from adapters.llm_astropods import AstropodsLLM
from adapters.llm_gemini import GeminiLLM
from adapters.llm_groq import GroqLLM


def _make_sample_case(
    *,
    state: CaseState = CaseState.VERIFIED,
    unit_price: Money | None = None,
    quantity: int = 1,
    findings: list[Finding] | None = None,
) -> tuple[Case, CaseSnapshot, LedgerEntry]:
    unit = unit_price or Money.of("28.50", "USD")
    total = unit * quantity
    prop = Proposal(
        proposal_id="prop_test1",
        mandate_id="mnd_test1",
        product_id="prod-gift-02",
        title="Hand-Poured Lavender Candle Set",
        quantity=quantity,
        claimed_unit_price=unit,
        claimed_total=total,
        claimed_seller_id="seller-a",
        claimed_payee_id="SELLER-A-VERIFIED",
        category="gifts",
    )
    snap = CaseSnapshot(
        snapshot_id="snap_test1",
        case_id="case_test1",
        checkpoint="C6_POST_CAPTURE_PROOFGUARD",
        mandate_id="mnd_test1",
        mandate_version=2,
        product_id="prod-gift-02",
        title="Hand-Poured Lavender Candle Set",
        quantity=quantity,
        unit_price=unit,
        total_amount=total,
        seller_id="seller-a",
        seller_name="Verified Boutique (Seller A)",
        seller_verified=True,
        payee_id="SELLER-A-VERIFIED",
        in_stock=True,
        category="gifts",
        paypal_order_id="ORD-PP-101",
        paypal_authorization_id="AUTH-PP-101" if state in {CaseState.AUTHORIZED, CaseState.CAPTURED, CaseState.VERIFIED, CaseState.FLAGGED} else None,
        paypal_capture_id="CAP-PP-101" if state in {CaseState.CAPTURED, CaseState.VERIFIED, CaseState.FLAGGED} else None,
        sources_used=["mandate", "proposal", "catalog", "paypal"],
    )
    case = Case(
        case_id="case_test1",
        mandate_id="mnd_test1",
        mandate_version=2,
        state=state,
        proposal=prop,
        approved_snapshot_id="snap_test1",
        latest_snapshot_id="snap_test1",
        paypal_order_id=snap.paypal_order_id,
        paypal_authorization_id=snap.paypal_authorization_id,
        paypal_capture_id=snap.paypal_capture_id,
        last_findings=findings or [],
    )
    created = utcnow() - timedelta(seconds=5)
    entry_hash = compute_entry_hash(
        seq=7,
        entry_id="led_test7",
        case_id="case_test1",
        mandate_id="mnd_test1",
        actor="proofguard",
        event_type=f"CASE_{state.value}",
        payload={"state": state.value},
        prev_hash=GENESIS_HASH,
        created_at=created,
    )
    entry = LedgerEntry(
        id="led_test7",
        seq=7,
        case_id="case_test1",
        mandate_id="mnd_test1",
        actor="proofguard",
        event_type=f"CASE_{state.value}",
        payload={"state": state.value},
        prev_hash=GENESIS_HASH,
        hash=entry_hash,
        created_at=created,
    )
    return case, snap, entry


def test_receipt_hash_is_deterministic_canonical_sha256_and_supports_jpy_kwd() -> None:
    import hashlib

    for unit, qty, expected_total in [
        (Money.of("28.50", "USD"), 1, "28.50 USD"),
        (Money.of("1500", "JPY"), 2, "3000 JPY"),
        (Money.of("12.345", "KWD"), 1, "12.345 KWD"),
    ]:
        case, snap, entry = _make_sample_case(unit_price=unit, quantity=qty)
        facts, _, _ = build_receipt_facts(case=case, snapshot=snap, latest_ledger_entry=entry)
        assert facts.total_amount == expected_total
        assert facts.unit_price == unit.to_str()
        assert facts.latest_ledger_hash == entry.hash

        expected_hash = hashlib.sha256(
            canonical_json(facts.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()
        assert compute_receipt_hash(facts) == expected_hash
        assert compute_receipt_hash(facts) == expected_hash


def test_all_case_states_have_distinct_non_misleading_narratives() -> None:
    narratives: dict[CaseState, str] = {}
    blocking_finding = Finding(
        code="EXCEEDS_MAX_TOTAL",
        severity=FindingSeverity.BLOCK,
        source="rule:max_total",
        message="Over cap",
        explanation="Blocked: exceeds cap.",
    )
    for st in CaseState:
        case, snap, entry = _make_sample_case(
            state=st,
            findings=[blocking_finding] if st in {CaseState.BLOCKED, CaseState.FLAGGED, CaseState.NEEDS_RECONFIRM} else [],
        )
        facts, _, _ = build_receipt_facts(case=case, snapshot=snap, latest_ledger_entry=entry)
        text = build_deterministic_receipt_narrative(facts)
        assert "28.50 USD" in text
        assert "SELLER-A-VERIFIED" in text
        assert st not in narratives
        narratives[st] = text

    # Every state must produce a distinct narrative
    assert len(set(narratives.values())) == len(list(CaseState))

    # AWAITING_APPROVAL and HELD must NEVER be labeled "Blocked"
    assert "blocked" not in narratives[CaseState.AWAITING_APPROVAL].lower()
    assert "awaiting user approval" in narratives[CaseState.AWAITING_APPROVAL].lower()
    assert "blocked" not in narratives[CaseState.HELD].lower()
    assert "held" in narratives[CaseState.HELD].lower()
    assert narratives[CaseState.VERIFIED].startswith("Verified ")
    assert narratives[CaseState.CAPTURED].startswith("Captured ")
    assert narratives[CaseState.BLOCKED].startswith("Blocked ")
    assert narratives[CaseState.FLAGGED].startswith("Flagged ")


def test_amount_mismatch_and_state_leak_detector() -> None:
    usd = Money.of("28.50", "USD")
    jpy = Money.of("1500", "JPY")
    kwd = Money.of("12.345", "KWD")

    assert not has_amount_mismatch_or_status_leak(
        "Verified 28.50 USD payment for case_test1 to SELLER-A-VERIFIED.",
        expected_amount=usd,
        expected_state=CaseState.VERIFIED,
    )
    # Minor unit integer leak ('2850 USD' or '$2850') MUST fail check
    assert has_amount_mismatch_or_status_leak(
        "Verified 2850 USD payment to SELLER-A-VERIFIED.",
        expected_amount=usd,
        expected_state=CaseState.VERIFIED,
    )
    # Wrong JPY decimal division ('15.00 JPY') MUST fail check
    assert has_amount_mismatch_or_status_leak(
        "Blocked 15.00 JPY order for violation.",
        expected_amount=jpy,
        expected_state=CaseState.BLOCKED,
    )
    # Wrong KWD rounding ('12.35 KWD') MUST fail check
    assert has_amount_mismatch_or_status_leak(
        "Verified 12.35 KWD order under mandate.",
        expected_amount=kwd,
        expected_state=CaseState.VERIFIED,
    )
    # Labeling AWAITING_APPROVAL as Blocked MUST fail check
    assert has_amount_mismatch_or_status_leak(
        "Blocked 28.50 USD order pending review.",
        expected_amount=usd,
        expected_state=CaseState.AWAITING_APPROVAL,
    )


@pytest.mark.asyncio
async def test_receipt_llm_narrative_uses_active_port_and_falls_back_on_leak_or_error() -> None:
    import json

    case, snap, entry = _make_sample_case(state=CaseState.AWAITING_APPROVAL)

    # 1. Valid GeminiLLM summary passes leak check -> llm-narrated
    gemini_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kw: SimpleNamespace(
                text='```json\n{"summary": "Awaiting your approval for 28.50 USD at SELLER-A-VERIFIED under mnd_test1."}\n```'
            )
        )
    )
    gemini = GeminiLLM(api_key="test", client=gemini_client, retry_base_delay=0.0)
    r_ok = await generate_intent_receipt(case=case, snapshot=snap, latest_ledger_entry=entry, llm=gemini)
    assert r_ok.narrative_source == "llm-narrated"
    assert "28.50 USD" in r_ok.narrative

    # 2. GroqLLM leaks minor units (2850 USD) or mislabels AWAITING_APPROVAL as Blocked -> deterministic fallback, SAME receipt_hash!
    class _LeakyGroq:
        async def create(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps({"summary": "Blocked 2850 USD at SELLER-A-VERIFIED."})
                        )
                    )
                ]
            )

    groq = GroqLLM(
        api_key="gsk_testsecret123456",
        client=SimpleNamespace(chat=SimpleNamespace(completions=_LeakyGroq())),
        retry_base_delay=0.0,
    )
    r_fallback = await generate_intent_receipt(case=case, snapshot=snap, latest_ledger_entry=entry, llm=groq)
    assert r_fallback.narrative_source == "deterministic-template"
    assert r_fallback.narrative == build_deterministic_receipt_narrative(r_fallback.facts)
    assert "blocked" not in r_fallback.narrative.lower()
    assert r_fallback.receipt_hash == r_ok.receipt_hash

    # 3. AstropodsLLM malformed JSON -> deterministic fallback cleanly
    import httpx

    astro = AstropodsLLM(
        gateway_url="https://astro.local",
        api_key="sk-astro-secret-1234",
        transport=httpx.MockTransport(
            lambda _req: httpx.Response(200, json={"choices": [{"message": {"content": "{bad json"}}]})
        ),
        retry_base_delay=0.0,
    )
    r_astro = await generate_intent_receipt(case=case, snapshot=snap, latest_ledger_entry=entry, llm=astro)
    assert r_astro.narrative_source == "deterministic-template"
    assert r_astro.receipt_hash == r_ok.receipt_hash
