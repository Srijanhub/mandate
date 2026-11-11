from datetime import timedelta

import httpx
import pytest
from mandate_core.domain.errors import IllegalTransitionError
from mandate_core.domain.models import CaseState, Mandate, MandateStatus, Money, utcnow
from mandate_core.ledger import verify_ledger_chain
from mandate_core.statemachine import Orchestrator
from mandate_core.workflows import build_proposal_from_product
from sqlalchemy import update

from adapters.catalog_mock import MockCatalog
from adapters.notifier_console import ConsoleNotifier
from adapters.paypal import MockPayPalProvider, PayPalPaymentProvider
from adapters.persistence import LedgerEntryRow, SqlAlchemyStateStore, create_engine_and_sessionmaker


async def _make_orchestrator():
    engine, factory = create_engine_and_sessionmaker("sqlite+aiosqlite:///:memory:")
    store = SqlAlchemyStateStore(engine, factory)
    await store.init_schema()
    catalog = MockCatalog()
    paypal = MockPayPalProvider()
    notifier = ConsoleNotifier()
    orch = Orchestrator(store=store, catalog=catalog, payment=paypal, notifier=notifier)
    return store, catalog, paypal, notifier, orch


@pytest.mark.asyncio
async def test_orchestrator_happy_path_and_illegal_transition_logs_ledger() -> None:
    store, catalog, _paypal, _notifier, orch = await _make_orchestrator()
    try:
        mandate = Mandate(
            intent_text="Candle under $60",
            max_total=Money.of("60.00", "USD"),
            expires_at=utcnow() + timedelta(hours=2),
            status=MandateStatus.DRAFT,
        )
        await orch.create_mandate_draft(mandate)
        await orch.confirm_mandate(mandate.mandate_id)

        product = await catalog.get("prod-gift-02")
        assert product is not None
        case = await orch.submit_proposal(build_proposal_from_product(mandate=mandate, product=product))
        assert case.state == CaseState.PROPOSED

        # Illegal transition (PROPOSED -> CAPTURED) must raise AND write ledger entry
        with pytest.raises(IllegalTransitionError):
            await orch.capture(case.case_id)

        entries, _ = await store.list_ledger(case_id=case.case_id)
        assert any(e.event_type == "ILLEGAL_TRANSITION_ATTEMPT" for e in entries)

        # Complete happy path -> VERIFIED
        case = await orch.lock_cart(case.case_id)
        assert case.state == CaseState.AWAITING_APPROVAL
        verified = await orch.approve_and_capture(case.case_id)
        assert verified.state == CaseState.VERIFIED
        assert verified.paypal_capture_id is not None

        verification = verify_ledger_chain(await store.iter_all_ledger())
        assert verification.valid is True
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_hold_drift_needs_reconfirm_and_recheck_worker_and_tamper_detection() -> None:
    store, catalog, _paypal, notifier, orch = await _make_orchestrator()
    try:
        mandate = Mandate(
            intent_text="Diffuser under $60",
            max_total=Money.of("60.00", "USD"),
            expires_at=utcnow() + timedelta(hours=2),
            status=MandateStatus.ACTIVE,
        )
        await store.save_mandate(mandate)
        product = await catalog.get("prod-home-03")
        assert product is not None
        case = await orch.submit_proposal(build_proposal_from_product(mandate=mandate, product=product))
        case = await orch.lock_cart(case.case_id)
        case = await orch.hold_case(case.case_id, duration_seconds=600)
        assert case.state == CaseState.HELD

        # Price drifts from $38.00 -> $48.00 (still <= $60)
        catalog.bump_price("prod-home-03", "48.00")
        processed = await orch.process_due_recheck_jobs()
        assert processed == 1

        drifted = await store.get_case(case.case_id)
        assert drifted is not None
        assert drifted.state == CaseState.NEEDS_RECONFIRM
        assert any(n.event == "NEEDS_RECONFIRM" for n in notifier.events)

        # User explicitly reconfirms the drifted price via approve_and_capture
        final_case = await orch.approve_and_capture(case.case_id)
        assert final_case.state == CaseState.VERIFIED

        # Tamper ledger seq=2 directly in DB -> verify_ledger_chain catches seq=2
        async with store.session_factory() as session:
            await session.execute(
                update(LedgerEntryRow).where(LedgerEntryRow.seq == 2).values(actor="evil")
            )
            await session.commit()
        check = verify_ledger_chain(await store.iter_all_ledger())
        assert check.valid is False
        assert check.first_broken_seq == 2
    finally:
        await store.dispose()


@pytest.mark.asyncio
async def test_paypal_http_provider_oauth_idempotency_and_void(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("PayPal-Request-Id")))
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(
                201,
                json={
                    "id": "ORD-PP-1",
                    "intent": "AUTHORIZE",
                    "status": "CREATED",
                    "purchase_units": [
                        {
                            "amount": {"currency_code": "USD", "value": "28.50"},
                            "payee": {"merchant_id": "SELLER-A"},
                        }
                    ],
                },
            )
        if request.url.path == "/v2/payments/authorizations/AUTH-PP-1/void":
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    orig_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)

    provider = PayPalPaymentProvider(client_id="cid", client_secret="csec", sandbox=True)
    ev = await provider.create_order(
        case_id="case-1",
        amount=Money.of("28.50", "USD"),
        payee_id="SELLER-A",
        description="Gift",
        request_id="req-id-1",
    )
    assert ev.order_id == "ORD-PP-1"
    assert ("POST", "/v2/checkout/orders", "req-id-1") in calls

    voided = await provider.void_authorization("AUTH-PP-1", request_id="req-void-1")
    assert voided.status == "VOIDED"
    assert ("POST", "/v2/payments/authorizations/AUTH-PP-1/void", "req-void-1") in calls
