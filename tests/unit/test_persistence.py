from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from mandate_core.domain.errors import IllegalTransitionError, PolicyBlockedError
from mandate_core.domain.models import (
    Case,
    CaseSnapshot,
    CaseState,
    Mandate,
    MandateStatus,
    Money,
    Proposal,
    RecheckJob,
    utcnow,
)
from mandate_core.ledger import GENESIS_HASH

from adapters.persistence import (
    SqlAlchemyStateStore,
    create_engine_and_sessionmaker,
    normalize_database_url,
    seed_demo_data,
)


def _make_sample_proposal(mandate_id: str) -> Proposal:
    return Proposal(
        mandate_id=mandate_id,
        product_id="prod-1",
        title="Test Candle",
        claimed_unit_price=Money.of("25.00", "USD"),
        claimed_total=Money.of("25.00", "USD"),
        claimed_seller_id="seller-1",
        claimed_payee_id="payee-1",
    )


def _make_sample_snapshot(case_id: str, checkpoint: str, snapshot_id: str) -> CaseSnapshot:
    return CaseSnapshot(
        snapshot_id=snapshot_id,
        case_id=case_id,
        checkpoint=checkpoint,
        mandate_id="mnd_test_1",
        mandate_version=1,
        product_id="prod-1",
        title="Test Candle",
        quantity=1,
        unit_price=Money.of("25.00", "USD"),
        total_amount=Money.of("25.00", "USD"),
        seller_id="seller-1",
        seller_name="Seller One",
        seller_verified=True,
        payee_id="payee-1",
        in_stock=True,
        category="gifts",
    )


@pytest.fixture
async def store():
    engine, factory = create_engine_and_sessionmaker("sqlite+aiosqlite:///:memory:")
    st = SqlAlchemyStateStore(engine, factory)
    await st.init_schema()
    yield st
    await st.dispose()


@pytest.mark.asyncio
async def test_database_url_normalization() -> None:
    assert normalize_database_url("postgres://u:p@localhost:5432/db") == "postgresql+asyncpg://u:p@localhost:5432/db"
    assert (
        normalize_database_url("postgresql://u:p@localhost:5432/db?sslmode=require")
        == "postgresql+asyncpg://u:p@localhost:5432/db?ssl=require"
    )
    assert normalize_database_url("sqlite+aiosqlite:///./test.db") == "sqlite+aiosqlite:///./test.db"


@pytest.mark.asyncio
async def test_mandate_crud_and_versioning(store: SqlAlchemyStateStore) -> None:
    mandate_v1 = Mandate(
        mandate_id="mnd_test_1",
        version=1,
        owner_id="alice",
        domain="shopping",
        intent_text="Initial intent",
        max_total=Money.of("50.00", "USD"),
        expires_at=utcnow() + timedelta(days=1),
        status=MandateStatus.DRAFT,
    )
    await store.save_mandate(mandate_v1)

    fetched_v1 = await store.get_mandate("mnd_test_1", version=1)
    assert fetched_v1 is not None
    assert fetched_v1.version == 1
    assert fetched_v1.status == MandateStatus.DRAFT

    # Save version 2
    mandate_v2 = Mandate(
        mandate_id="mnd_test_1",
        version=2,
        owner_id="alice",
        domain="shopping",
        intent_text="Confirmed intent",
        max_total=Money.of("50.00", "USD"),
        expires_at=utcnow() + timedelta(days=1),
        status=MandateStatus.ACTIVE,
    )
    await store.save_mandate(mandate_v2)

    # get_mandate without version gets highest version
    latest = await store.get_mandate("mnd_test_1")
    assert latest is not None
    assert latest.version == 2
    assert latest.status == MandateStatus.ACTIVE

    active = await store.get_active_mandate(owner_id="alice")
    assert active is not None
    assert active.mandate_id == "mnd_test_1"
    assert active.version == 2

    mandates_list = await store.list_mandates(owner_id="alice")
    assert len(mandates_list) == 2


@pytest.mark.asyncio
async def test_case_and_snapshot_lifecycle(store: SqlAlchemyStateStore) -> None:
    case = Case(
        case_id="case_100",
        mandate_id="mnd_test_1",
        state=CaseState.PROPOSED,
        proposal=_make_sample_proposal("mnd_test_1"),
    )
    await store.save_case(case)

    fetched = await store.get_case("case_100")
    assert fetched is not None
    assert fetched.state == CaseState.PROPOSED

    # Save snapshots
    s1 = _make_sample_snapshot("case_100", "C1_PROPOSAL", "snp_1")
    await store.save_snapshot(s1)

    s2 = _make_sample_snapshot("case_100", "C3_INTENT_AUTHORIZED", "snp_2")
    await store.save_snapshot(s2)

    by_ckpt = await store.get_snapshot_at_checkpoint("case_100", "C1_PROPOSAL")
    assert by_ckpt is not None
    assert by_ckpt.snapshot_id == "snp_1"

    # Deterministic tie-breaker selects snp_2
    latest_snp = await store.get_latest_snapshot("case_100")
    assert latest_snp is not None
    assert latest_snp.snapshot_id == "snp_2"

    all_snps = await store.list_snapshots("case_100")
    assert len(all_snps) == 2


@pytest.mark.asyncio
async def test_ledger_append_hash_chain_and_lookups(store: SqlAlchemyStateStore) -> None:
    e1 = await store.append_ledger(
        case_id="case_1",
        mandate_id="mnd_1",
        actor="user",
        event_type="MANDATE_CREATED",
        payload={"note": "first entry"},
    )
    assert e1.seq == 1
    assert e1.prev_hash == GENESIS_HASH

    e2 = await store.append_ledger(
        case_id="case_1",
        mandate_id="mnd_1",
        actor="policy_engine",
        event_type="POLICY_ALLOWED",
        payload={"decision": "allow"},
    )
    assert e2.seq == 2
    assert e2.prev_hash == e1.hash

    # Single lookup by id and by seq
    found_by_id = await store.get_ledger_entry(e1.id)
    assert found_by_id is not None
    assert found_by_id.id == e1.id

    found_by_seq = await store.get_ledger_by_seq(2)
    assert found_by_seq is not None
    assert found_by_seq.hash == e2.hash

    # Verify chain integrity
    verif = await store.verify_ledger_integrity()
    assert verif.valid is True


@pytest.mark.asyncio
async def test_ledger_concurrency_safe_sequences(store: SqlAlchemyStateStore) -> None:
    """Ensure concurrent ledger writes never collide on sequence number."""
    async def worker(idx: int) -> None:
        await store.append_ledger(
            case_id=f"case_{idx}",
            mandate_id="mnd_1",
            actor=f"worker_{idx}",
            event_type="CONCURRENT_EVENT",
            payload={"idx": idx},
        )

    tasks = [worker(i) for i in range(15)]
    await asyncio.gather(*tasks)

    entries = await store.iter_all_ledger()
    assert len(entries) == 15
    seqs = [e.seq for e in entries]
    assert seqs == list(range(1, 16))

    verif = await store.verify_ledger_integrity()
    assert verif.valid is True


@pytest.mark.asyncio
async def test_atomic_transaction_rollback_and_error_commit(store: SqlAlchemyStateStore) -> None:
    # 1. BaseException rolls back
    with pytest.raises(RuntimeError):
        async with store.atomic():
            c = Case(
                case_id="case_err",
                mandate_id="mnd_1",
                state=CaseState.PROPOSED,
                proposal=_make_sample_proposal("mnd_1"),
            )
            await store.save_case(c)
            raise RuntimeError("Boom")

    assert await store.get_case("case_err") is None

    # 2. IllegalTransitionError commits audit entry
    with pytest.raises(IllegalTransitionError):
        async with store.atomic():
            await store.append_ledger(
                case_id="case_audit",
                mandate_id="mnd_1",
                actor="user",
                event_type="ILLEGAL_TRANSITION_ATTEMPT",
                payload={"attempted": "CAPTURED"},
            )
            raise IllegalTransitionError("Illegal transition from PROPOSED to CAPTURED")

    entries, total = await store.list_ledger(case_id="case_audit")
    assert total == 1
    assert entries[0].event_type == "ILLEGAL_TRANSITION_ATTEMPT"

    # 3. PolicyBlockedError commits audit entry
    with pytest.raises(PolicyBlockedError):
        async with store.atomic():
            await store.append_ledger(
                case_id="case_block",
                mandate_id="mnd_1",
                actor="policy_engine",
                event_type="POLICY_BLOCKED",
                payload={"reasons": ["Amount exceeds cap"]},
            )
            raise PolicyBlockedError("Policy blocked", details={"reasons": ["Amount exceeds cap"]})

    entries_blocked, total_blocked = await store.list_ledger(case_id="case_block")
    assert total_blocked == 1
    assert entries_blocked[0].event_type == "POLICY_BLOCKED"


@pytest.mark.asyncio
async def test_webhook_idempotency_persisted(store: SqlAlchemyStateStore) -> None:
    payload = {"id": "WH-999", "event_type": "PAYMENT.CAPTURE.COMPLETED"}
    # First call records and commits
    first = await store.record_webhook_if_new("WH-999", "PAYMENT.CAPTURE.COMPLETED", payload)
    assert first is True

    # Second call detects duplicate and returns False
    second = await store.record_webhook_if_new("WH-999", "PAYMENT.CAPTURE.COMPLETED", payload)
    assert second is False


@pytest.mark.asyncio
async def test_recheck_queue_workflow(store: SqlAlchemyStateStore) -> None:
    due_job = RecheckJob(
        job_id="job_1",
        case_id="case_1",
        checkpoint="C7_RECHECK",
        status="PENDING",
        run_after=utcnow() - timedelta(seconds=10),
    )
    future_job = RecheckJob(
        job_id="job_2",
        case_id="case_2",
        checkpoint="C7_RECHECK",
        status="PENDING",
        run_after=utcnow() + timedelta(minutes=10),
    )
    await store.enqueue_recheck_job(due_job)
    await store.enqueue_recheck_job(future_job)

    claimed = await store.claim_due_recheck_jobs(now=utcnow(), limit=5)
    assert len(claimed) == 1
    assert claimed[0].job_id == "job_1"
    assert claimed[0].status == "RUNNING"
    assert claimed[0].attempts == 1

    await store.finish_recheck_job("job_1", status="COMPLETED")


@pytest.mark.asyncio
async def test_check_health_and_seed_demo_data(store: SqlAlchemyStateStore) -> None:
    # 1. Fast O(1) default health check on clean store
    h1 = await store.check_health()
    assert h1["status"] == "healthy"
    assert h1["dialect"] == "sqlite"
    assert h1["counts"]["mandates"] == 0
    assert h1["latest_ledger_seq"] == 0
    assert "ledger_valid" not in h1

    # 2. Opt-in ledger verification
    h1_opt = await store.check_health(verify_ledger=True)
    assert h1_opt["ledger_valid"] is True

    # 3. Seed demo data (atomic + Channel3 compatibility)
    res = await seed_demo_data(store)
    assert res["seeded"] is True
    assert "mnd_demo_shopping_01" in res["seeded_mandates"]
    assert res["seeded_ledger"] is True

    shopping = await store.get_mandate("mnd_demo_shopping_01")
    assert shopping is not None
    assert shopping.allowed_sellers == []  # Open to Mock and Channel3 verified sellers
    assert shopping.require_verified_seller is True
    assert shopping.blocked_sellers == ["SELLER-B-ATTACKER"]

    # 4. Idempotent second seed
    res2 = await seed_demo_data(store)
    assert res2["seeded"] is False

    # 5. Health check after seed
    h2 = await store.check_health(verify_ledger=True)
    assert h2["counts"]["mandates"] >= 2
    assert h2["counts"]["ledger_entries"] >= 1
    assert h2["latest_ledger_seq"] >= 1
    assert h2["ledger_valid"] is True

    # 6. Error handling test on disconnected store
    engine_bad, factory_bad = create_engine_and_sessionmaker("sqlite+aiosqlite:///:memory:")
    store_bad = SqlAlchemyStateStore(engine_bad, factory_bad)
    await store_bad.dispose()
    err_health = await store_bad.check_health()
    assert err_health["status"] == "unhealthy"
    assert "error" in err_health


@pytest.mark.asyncio
async def test_init_schema_idempotent_on_existing_database(store: SqlAlchemyStateStore) -> None:
    """Ensure init_schema creates indexes idempotently on existing databases without error."""
    await store.init_schema()
    # Write a mandate and check health to confirm functionality
    m = Mandate(
        mandate_id="mnd_init_test",
        version=1,
        owner_id="bob",
        domain="shopping",
        intent_text="Init test",
        max_total=Money.of("30.00", "USD"),
        expires_at=utcnow() + timedelta(days=1),
        status=MandateStatus.ACTIVE,
    )
    await store.save_mandate(m)
    assert (await store.get_mandate("mnd_init_test")) is not None
