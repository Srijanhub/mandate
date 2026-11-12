from __future__ import annotations

import asyncio
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mandate_core.domain.errors import IllegalTransitionError, PolicyBlockedError, ValidationError
from mandate_core.domain.models import (
    Case,
    CaseSnapshot,
    CaseState,
    LedgerEntry,
    Mandate,
    RecheckJob,
    new_id,
    utcnow,
)
from mandate_core.ledger import GENESIS_HASH, compute_entry_hash
from mandate_core.statemachine.transitions import OPEN_CASE_STATES
from sqlalchemy import Select, event, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from adapters.errors import redact_secrets

from .models import (
    Base,
    CaseRow,
    LedgerEntryRow,
    MandateRow,
    OtpChallengeRow,
    RecheckJobRow,
    SnapshotRow,
    UserRow,
    WebhookEventRow,
)

_CURRENT_SESSION: ContextVar[AsyncSession | None] = ContextVar("mandate_current_session", default=None)
PG_LEDGER_ADVISORY_LOCK_ID: int = 73918273


def normalize_database_url(database_url: str) -> str:
    """Normalize Render/Heroku postgres:// or postgresql:// URLs for asyncpg."""
    url = database_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgresql+asyncpg://") and "sslmode=" in url:
        url = url.replace("sslmode=", "ssl=")
    return url


def create_engine_and_sessionmaker(
    database_url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_recycle: int = 1800,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    normalized_url = normalize_database_url(database_url)
    if normalized_url.startswith("sqlite"):
        is_memory = ":memory:" in normalized_url or normalized_url.endswith("///")
        if ":///" in normalized_url and not is_memory:
            raw_path = normalized_url.split(":///", 1)[1]
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(normalized_url, echo=False)

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=10000;")
            if not is_memory:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.close()
    else:
        engine = create_async_engine(
            normalized_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


class SqlAlchemyStateStore:
    """
    Async SQLAlchemy StateStore supporting PostgreSQL (advisory lock + FOR UPDATE SKIP LOCKED)
    and SQLite (serialized async write lock + WAL mode) behind the Core StateStore protocol.
    """

    def __init__(self, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.engine = engine
        self.session_factory = session_factory
        self.is_postgres = engine.dialect.name == "postgresql"
        self._sqlite_write_lock = asyncio.Lock()

    async def init_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            def _ensure_indexes_exist(sync_conn: Any) -> None:
                for table in Base.metadata.tables.values():
                    for idx in table.indexes:
                        try:
                            idx.create(sync_conn, checkfirst=True)
                        except Exception:
                            pass

            await conn.run_sync(_ensure_indexes_exist)

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def _write_lock_if_sqlite_standalone(self) -> AsyncIterator[None]:
        """Acquire _sqlite_write_lock only for standalone writes outside atomic()."""
        if not self.is_postgres and _CURRENT_SESSION.get() is None:
            async with self._sqlite_write_lock:
                yield
        else:
            yield

    @asynccontextmanager
    async def atomic(self) -> AsyncIterator[None]:
        existing = _CURRENT_SESSION.get()
        if existing is not None:
            yield
            return

        lock = self._sqlite_write_lock if not self.is_postgres else None
        if lock is not None:
            await lock.acquire()
        try:
            async with self.session_factory() as session:
                token = _CURRENT_SESSION.set(session)
                try:
                    yield
                except (IllegalTransitionError, PolicyBlockedError):
                    await session.commit()
                    raise
                except BaseException:
                    await session.rollback()
                    raise
                else:
                    await session.commit()
                finally:
                    _CURRENT_SESSION.reset(token)
        finally:
            if lock is not None:
                lock.release()

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        current = _CURRENT_SESSION.get()
        if current is not None:
            yield current
            return
        async with self.session_factory() as session:
            yield session

    # ------------------------------------------------------------------
    # Mandates
    # ------------------------------------------------------------------

    async def save_mandate(self, mandate: Mandate) -> Mandate:
        payload = mandate.model_dump(mode="json")
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                row = await session.get(MandateRow, (mandate.mandate_id, mandate.version))
                if row is None:
                    row = MandateRow(
                        mandate_id=mandate.mandate_id,
                        version=mandate.version,
                        owner_id=mandate.owner_id,
                        domain=mandate.domain,
                        status=mandate.status.value,
                        data_json=payload,
                        created_at=mandate.created_at,
                        updated_at=mandate.updated_at,
                    )
                    session.add(row)
                else:
                    row.owner_id = mandate.owner_id
                    row.domain = mandate.domain
                    row.status = mandate.status.value
                    row.data_json = payload
                    row.updated_at = mandate.updated_at
                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
        return mandate

    async def get_mandate(self, mandate_id: str, *, version: int | None = None) -> Mandate | None:
        async with self._session() as session:
            stmt: Select[tuple[MandateRow]] = select(MandateRow).where(
                MandateRow.mandate_id == mandate_id
            )
            if version is not None:
                stmt = stmt.where(MandateRow.version == version)
            else:
                stmt = stmt.order_by(MandateRow.version.desc()).limit(1)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return Mandate.model_validate(row.data_json) if row else None

    async def get_latest_mandate(self, *, owner_id: str | None = None) -> Mandate | None:
        async with self._session() as session:
            stmt = select(MandateRow).order_by(MandateRow.updated_at.desc(), MandateRow.version.desc()).limit(1)
            if owner_id:
                stmt = stmt.where(MandateRow.owner_id == owner_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return Mandate.model_validate(row.data_json) if row else None

    async def get_active_mandate(self, *, owner_id: str | None = None) -> Mandate | None:
        async with self._session() as session:
            stmt = (
                select(MandateRow)
                .where(MandateRow.status == "ACTIVE")
                .order_by(MandateRow.updated_at.desc(), MandateRow.version.desc())
                .limit(1)
            )
            if owner_id:
                stmt = stmt.where(MandateRow.owner_id == owner_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return Mandate.model_validate(row.data_json) if row else None

    async def list_mandates(self, *, owner_id: str | None = None, limit: int = 50) -> list[Mandate]:
        async with self._session() as session:
            stmt = select(MandateRow).order_by(MandateRow.updated_at.desc(), MandateRow.version.desc()).limit(limit)
            if owner_id:
                stmt = stmt.where(MandateRow.owner_id == owner_id)
            rows = (await session.execute(stmt)).scalars().all()
            return [Mandate.model_validate(r.data_json) for r in rows]

    # ------------------------------------------------------------------
    # Cases & Snapshots
    # ------------------------------------------------------------------

    async def save_case(self, case: Case) -> Case:
        payload = case.model_dump(mode="json")
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                row = await session.get(CaseRow, case.case_id)
                if row is None:
                    row = CaseRow(
                        case_id=case.case_id,
                        mandate_id=case.mandate_id,
                        state=case.state.value,
                        data_json=payload,
                        created_at=case.created_at,
                        updated_at=case.updated_at,
                    )
                    session.add(row)
                else:
                    row.mandate_id = case.mandate_id
                    row.state = case.state.value
                    row.data_json = payload
                    row.updated_at = case.updated_at
                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
        return case

    async def get_case(self, case_id: str, *, for_update: bool = False) -> Case | None:
        async with self._session() as session:
            stmt = select(CaseRow).where(CaseRow.case_id == case_id)
            if for_update and self.is_postgres:
                stmt = stmt.with_for_update()
            row = (await session.execute(stmt)).scalar_one_or_none()
            return Case.model_validate(row.data_json) if row else None

    async def get_latest_case(self, *, owner_id: str | None = None) -> Case | None:
        async with self._session() as session:
            stmt = select(CaseRow).order_by(CaseRow.updated_at.desc()).limit(1)
            if owner_id:
                owned_mandates = select(MandateRow.mandate_id).where(MandateRow.owner_id == owner_id)
                stmt = stmt.where(CaseRow.mandate_id.in_(owned_mandates))
            row = (await session.execute(stmt)).scalar_one_or_none()
            return Case.model_validate(row.data_json) if row else None

    async def list_cases(
        self,
        *,
        mandate_id: str | None = None,
        owner_id: str | None = None,
        state: CaseState | None = None,
        limit: int = 50,
    ) -> list[Case]:
        async with self._session() as session:
            stmt = select(CaseRow).order_by(CaseRow.updated_at.desc()).limit(limit)
            if mandate_id:
                stmt = stmt.where(CaseRow.mandate_id == mandate_id)
            if owner_id:
                owned_mandates = select(MandateRow.mandate_id).where(MandateRow.owner_id == owner_id)
                stmt = stmt.where(CaseRow.mandate_id.in_(owned_mandates))
            if state:
                stmt = stmt.where(CaseRow.state == state.value)
            rows = (await session.execute(stmt)).scalars().all()
            return [Case.model_validate(r.data_json) for r in rows]

    async def list_open_cases(self, *, owner_id: str | None = None) -> list[Case]:
        open_values = [s.value for s in OPEN_CASE_STATES]
        async with self._session() as session:
            stmt = select(CaseRow).where(CaseRow.state.in_(open_values)).order_by(CaseRow.created_at.asc())
            if owner_id:
                owned_mandates = select(MandateRow.mandate_id).where(MandateRow.owner_id == owner_id)
                stmt = stmt.where(CaseRow.mandate_id.in_(owned_mandates))
            rows = (await session.execute(stmt)).scalars().all()
            return [Case.model_validate(r.data_json) for r in rows]

    async def list_held_or_authorized_cases(self) -> list[Case]:
        async with self._session() as session:
            stmt = (
                select(CaseRow)
                .where(CaseRow.state.in_([CaseState.HELD.value, CaseState.AUTHORIZED.value]))
                .order_by(CaseRow.updated_at.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [Case.model_validate(r.data_json) for r in rows]

    async def save_snapshot(self, snapshot: CaseSnapshot) -> CaseSnapshot:
        payload = snapshot.model_dump(mode="json")
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                row = SnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    case_id=snapshot.case_id,
                    checkpoint=snapshot.checkpoint,
                    data_json=payload,
                    created_at=snapshot.created_at,
                )
                session.add(row)
                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
        return snapshot

    async def get_snapshot(self, snapshot_id: str) -> CaseSnapshot | None:
        async with self._session() as session:
            row = await session.get(SnapshotRow, snapshot_id)
            return CaseSnapshot.model_validate(row.data_json) if row else None

    async def get_snapshot_at_checkpoint(self, case_id: str, checkpoint: str) -> CaseSnapshot | None:
        async with self._session() as session:
            stmt = (
                select(SnapshotRow)
                .where(SnapshotRow.case_id == case_id, SnapshotRow.checkpoint == checkpoint)
                .order_by(SnapshotRow.created_at.desc(), SnapshotRow.snapshot_id.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return CaseSnapshot.model_validate(row.data_json) if row else None

    async def get_latest_snapshot(self, case_id: str) -> CaseSnapshot | None:
        async with self._session() as session:
            stmt = (
                select(SnapshotRow)
                .where(SnapshotRow.case_id == case_id)
                .order_by(SnapshotRow.created_at.desc(), SnapshotRow.snapshot_id.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return CaseSnapshot.model_validate(row.data_json) if row else None

    async def list_snapshots(self, case_id: str) -> list[CaseSnapshot]:
        async with self._session() as session:
            stmt = (
                select(SnapshotRow)
                .where(SnapshotRow.case_id == case_id)
                .order_by(SnapshotRow.created_at.asc(), SnapshotRow.snapshot_id.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [CaseSnapshot.model_validate(r.data_json) for r in rows]

    # ------------------------------------------------------------------
    # Hash-Chained Ledger (Advisory Lock on Postgres, Mutex on SQLite)
    # ------------------------------------------------------------------

    async def append_ledger(
        self,
        *,
        case_id: str | None,
        mandate_id: str | None,
        actor: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> LedgerEntry:
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                if self.is_postgres:
                    await session.execute(text(f"SELECT pg_advisory_xact_lock({PG_LEDGER_ADVISORY_LOCK_ID})"))

                last_row = (
                    await session.execute(
                        select(LedgerEntryRow.seq, LedgerEntryRow.hash)
                        .order_by(LedgerEntryRow.seq.desc())
                        .limit(1)
                    )
                ).first()

                seq = (last_row[0] + 1) if last_row else 1
                prev_hash = last_row[1] if last_row else GENESIS_HASH
                entry_id = new_id("led")
                created_at = utcnow()
                entry_hash = compute_entry_hash(
                    seq=seq,
                    entry_id=entry_id,
                    case_id=case_id,
                    mandate_id=mandate_id,
                    actor=actor,
                    event_type=event_type,
                    payload=payload,
                    prev_hash=prev_hash,
                    created_at=created_at,
                )

                row = LedgerEntryRow(
                    id=entry_id,
                    seq=seq,
                    case_id=case_id,
                    mandate_id=mandate_id,
                    actor=actor,
                    event_type=event_type,
                    payload=payload,
                    prev_hash=prev_hash,
                    hash=entry_hash,
                    created_at=created_at,
                )
                session.add(row)
                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()

                return LedgerEntry(
                    id=entry_id,
                    seq=seq,
                    case_id=case_id,
                    mandate_id=mandate_id,
                    actor=actor,
                    event_type=event_type,
                    payload=payload,
                    prev_hash=prev_hash,
                    hash=entry_hash,
                    created_at=created_at,
                )

    def _map_ledger_row(self, r: LedgerEntryRow) -> LedgerEntry:
        ts = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)
        return LedgerEntry(
            id=r.id,
            seq=r.seq,
            case_id=r.case_id,
            mandate_id=r.mandate_id,
            actor=r.actor,
            event_type=r.event_type,
            payload=r.payload,
            prev_hash=r.prev_hash,
            hash=r.hash,
            created_at=ts,
        )

    async def get_ledger_entry(self, entry_id: str) -> LedgerEntry | None:
        async with self._session() as session:
            row = await session.get(LedgerEntryRow, entry_id)
            return self._map_ledger_row(row) if row else None

    async def get_ledger_by_seq(self, seq: int) -> LedgerEntry | None:
        async with self._session() as session:
            stmt = select(LedgerEntryRow).where(LedgerEntryRow.seq == seq)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return self._map_ledger_row(row) if row else None

    def _ledger_owner_clause(self, owner_id: str) -> Any:
        owned_mandates = select(MandateRow.mandate_id).where(MandateRow.owner_id == owner_id)
        owned_cases = select(CaseRow.case_id).where(CaseRow.mandate_id.in_(owned_mandates))
        return or_(
            LedgerEntryRow.actor == owner_id,
            LedgerEntryRow.mandate_id.in_(owned_mandates),
            LedgerEntryRow.case_id.in_(owned_cases),
        )

    async def list_ledger(
        self,
        *,
        case_id: str | None = None,
        mandate_id: str | None = None,
        owner_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
        sort_dir: str = "desc",
    ) -> tuple[list[LedgerEntry], int]:
        async with self._session() as session:
            base = select(LedgerEntryRow)
            cnt_q = select(func.count()).select_from(LedgerEntryRow)
            if case_id:
                base = base.where(LedgerEntryRow.case_id == case_id)
                cnt_q = cnt_q.where(LedgerEntryRow.case_id == case_id)
            if mandate_id:
                base = base.where(LedgerEntryRow.mandate_id == mandate_id)
                cnt_q = cnt_q.where(LedgerEntryRow.mandate_id == mandate_id)
            if owner_id:
                clause = self._ledger_owner_clause(owner_id)
                base = base.where(clause)
                cnt_q = cnt_q.where(clause)
            if event_type:
                base = base.where(LedgerEntryRow.event_type == event_type)
                cnt_q = cnt_q.where(LedgerEntryRow.event_type == event_type)

            order_col = LedgerEntryRow.seq.asc() if sort_dir == "asc" else LedgerEntryRow.seq.desc()
            rows = (
                await session.execute(base.order_by(order_col).limit(limit).offset(offset))
            ).scalars().all()
            total = int((await session.execute(cnt_q)).scalar_one())
            return [self._map_ledger_row(r) for r in rows], total

    async def iter_all_ledger(self, *, owner_id: str | None = None) -> list[LedgerEntry]:
        async with self._session() as session:
            stmt = select(LedgerEntryRow).order_by(LedgerEntryRow.seq.asc())
            if owner_id:
                stmt = stmt.where(self._ledger_owner_clause(owner_id))
            rows = (await session.execute(stmt)).scalars().all()
            return [self._map_ledger_row(r) for r in rows]

    async def verify_ledger_integrity(self) -> Any:
        """Verify the full cryptographic SHA-256 chain of the audit ledger."""
        from mandate_core.ledger import verify_ledger_chain

        entries = await self.iter_all_ledger()
        return verify_ledger_chain(entries)

    # ------------------------------------------------------------------
    # Recheck Job Queue (SELECT ... FOR UPDATE SKIP LOCKED on Postgres)
    # ------------------------------------------------------------------

    async def enqueue_recheck_job(self, job: RecheckJob) -> RecheckJob:
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                row = RecheckJobRow(
                    job_id=job.job_id,
                    case_id=job.case_id,
                    checkpoint=job.checkpoint,
                    status=job.status,
                    run_after=job.run_after,
                    attempts=job.attempts,
                    last_error=job.last_error,
                    created_at=job.created_at,
                )
                session.add(row)
                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
        return job

    async def claim_due_recheck_jobs(self, *, now: datetime, limit: int = 10) -> list[RecheckJob]:
        async with self.atomic():
            async with self._session() as session:
                stmt = (
                    select(RecheckJobRow)
                    .where(RecheckJobRow.status == "PENDING", RecheckJobRow.run_after <= now)
                    .order_by(RecheckJobRow.run_after.asc())
                    .limit(limit)
                )
                if self.is_postgres:
                    stmt = stmt.with_for_update(skip_locked=True)

                rows = (await session.execute(stmt)).scalars().all()
                claimed: list[RecheckJob] = []
                for r in rows:
                    r.status = "RUNNING"
                    r.attempts += 1
                    claimed.append(
                        RecheckJob(
                            job_id=r.job_id,
                            case_id=r.case_id,
                            checkpoint=r.checkpoint,
                            status="RUNNING",
                            run_after=r.run_after,
                            attempts=r.attempts,
                            last_error=r.last_error,
                            created_at=r.created_at,
                        )
                    )
                await session.flush()
                return claimed

    async def finish_recheck_job(
        self, job_id: str, *, status: str, error: str | None = None
    ) -> None:
        async with self.atomic():
            async with self._session() as session:
                row = await session.get(RecheckJobRow, job_id)
                if row is not None:
                    row.status = status
                    row.last_error = error
                    await session.flush()

    # ------------------------------------------------------------------
    # Webhook Idempotency (Atomic Deduplication + Commit)
    # ------------------------------------------------------------------

    async def record_webhook_if_new(
        self, event_id: str, event_type: str, payload: dict[str, Any]
    ) -> bool:
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                if self.is_postgres:
                    stmt = (
                        pg_insert(WebhookEventRow)
                        .values(
                            event_id=event_id,
                            event_type=event_type,
                            payload=payload,
                            received_at=utcnow(),
                        )
                        .on_conflict_do_nothing(index_elements=["event_id"])
                    )
                    res = await session.execute(stmt)
                    inserted = bool(res.rowcount == 1)
                else:
                    stmt = (
                        sqlite_insert(WebhookEventRow)
                        .values(
                            event_id=event_id,
                            event_type=event_type,
                            payload=payload,
                            received_at=utcnow(),
                        )
                        .on_conflict_do_nothing(index_elements=["event_id"])
                    )
                    res = await session.execute(stmt)
                    inserted = bool(res.rowcount == 1)

                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
                return inserted

    # ------------------------------------------------------------------
    # Diagnostics & Seeding
    # ------------------------------------------------------------------

    async def check_health(self, *, verify_ledger: bool = False) -> dict[str, Any]:
        """Verify database connectivity, query latency, table row counts, and optional ledger integrity."""
        start = asyncio.get_running_loop().time()
        try:
            async with self._session() as session:
                await session.execute(text("SELECT 1"))
                latency_ms = round((asyncio.get_running_loop().time() - start) * 1000, 2)

                mandate_cnt = (
                    await session.execute(select(func.count()).select_from(MandateRow))
                ).scalar_one()
                case_cnt = (
                    await session.execute(select(func.count()).select_from(CaseRow))
                ).scalar_one()
                ledger_cnt = (
                    await session.execute(select(func.count()).select_from(LedgerEntryRow))
                ).scalar_one()
                recheck_cnt = (
                    await session.execute(
                        select(func.count())
                        .select_from(RecheckJobRow)
                        .where(RecheckJobRow.status == "PENDING")
                    )
                ).scalar_one()

                last_ledger = (
                    await session.execute(
                        select(LedgerEntryRow.seq, LedgerEntryRow.hash)
                        .order_by(LedgerEntryRow.seq.desc())
                        .limit(1)
                    )
                ).first()

            res: dict[str, Any] = {
                "status": "healthy",
                "dialect": self.engine.dialect.name,
                "latency_ms": latency_ms,
                "counts": {
                    "mandates": int(mandate_cnt),
                    "cases": int(case_cnt),
                    "ledger_entries": int(ledger_cnt),
                    "pending_rechecks": int(recheck_cnt),
                },
                "latest_ledger_seq": int(last_ledger[0]) if last_ledger else 0,
                "latest_ledger_hash": str(last_ledger[1]) if last_ledger else None,
            }

            if verify_ledger:
                ledger_check = await self.verify_ledger_integrity()
                res["ledger_valid"] = bool(ledger_check.valid)

            return res
        except Exception as exc:
            return {
                "status": "unhealthy",
                "dialect": getattr(self.engine.dialect, "name", "unknown"),
                "error": redact_secrets(str(exc))[:240],
            }

    async def seed_demo_data(
        self,
        *,
        seller_a_id: str = "SELLER-A-VERIFIED",
        seller_b_id: str = "SELLER-B-ATTACKER",
    ) -> dict[str, Any]:
        """Idempotently seeds initial demo mandates and genesis audit trail."""
        from .seed import seed_demo_data

        return await seed_demo_data(self, seller_a_id=seller_a_id, seller_b_id=seller_b_id)

    # ------------------------------------------------------------------
    # Users & Mobile OTP Challenges (Google + Phone Auth)
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    def _map_user_row(self, row: UserRow) -> dict[str, Any]:
        return {
            "user_id": row.user_id,
            "email": row.email,
            "phone_number": row.phone_number,
            "google_sub": row.google_sub,
            "display_name": row.display_name,
            "avatar_url": row.avatar_url,
            "role": row.role,
            "auth_providers": list(row.auth_providers_json or []),
            "created_at": self._ensure_utc(row.created_at),
            "last_login_at": self._ensure_utc(row.last_login_at),
        }

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            row = await session.get(UserRow, user_id)
            return self._map_user_row(row) if row else None

    async def upsert_google_user(
        self,
        *,
        google_sub: str,
        email: str,
        display_name: str,
        avatar_url: str | None = None,
        link_user_id: str | None = None,
    ) -> dict[str, Any]:
        norm_email = email.strip().lower()
        now = utcnow()
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                by_sub = (
                    await session.execute(select(UserRow).where(UserRow.google_sub == google_sub))
                ).scalar_one_or_none()
                by_email = (
                    await session.execute(select(UserRow).where(UserRow.email == norm_email))
                ).scalar_one_or_none()

                if by_sub is not None and by_email is not None and by_sub.user_id != by_email.user_id:
                    raise ValidationError("Google email is already associated with another user account")

                row = by_sub or by_email
                if row is None and link_user_id:
                    row = await session.get(UserRow, link_user_id)
                    if row is not None and (by_sub is not None or by_email is not None):
                        raise ValidationError("Google account is already linked to another user")

                if row is None:
                    row = UserRow(
                        user_id=new_id("usr"),
                        email=norm_email,
                        phone_number=None,
                        google_sub=google_sub,
                        display_name=display_name.strip() or norm_email.split("@", 1)[0],
                        avatar_url=avatar_url,
                        role="user",
                        auth_providers_json=["google"],
                        created_at=now,
                        updated_at=now,
                        last_login_at=now,
                    )
                    session.add(row)
                else:
                    if link_user_id and row.user_id != link_user_id:
                        raise ValidationError("Google account is already linked to another user")
                    if row.google_sub is not None and row.google_sub != google_sub:
                        raise ValidationError("This user account is already linked to a different Google account")
                    providers = list(row.auth_providers_json or [])
                    if "google" not in providers:
                        providers.append("google")
                    row.google_sub = google_sub
                    row.email = norm_email
                    if display_name.strip():
                        row.display_name = display_name.strip()
                    if avatar_url:
                        row.avatar_url = avatar_url
                    row.auth_providers_json = providers
                    row.updated_at = now
                    row.last_login_at = now

                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
                return self._map_user_row(row)

    async def upsert_phone_user(
        self,
        *,
        phone_number: str,
        display_name: str | None = None,
        link_user_id: str | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                by_phone = (
                    await session.execute(select(UserRow).where(UserRow.phone_number == phone_number))
                ).scalar_one_or_none()

                if link_user_id and by_phone is not None and by_phone.user_id != link_user_id:
                    raise ValidationError("Phone number is already linked to another user account")

                row = by_phone
                if row is None and link_user_id:
                    row = await session.get(UserRow, link_user_id)

                if row is None:
                    fallback_name = f"User {phone_number[-4:]}"
                    row = UserRow(
                        user_id=new_id("usr"),
                        email=None,
                        phone_number=phone_number,
                        google_sub=None,
                        display_name=(display_name or "").strip() or fallback_name,
                        avatar_url=None,
                        role="user",
                        auth_providers_json=["phone"],
                        created_at=now,
                        updated_at=now,
                        last_login_at=now,
                    )
                    session.add(row)
                else:
                    providers = list(row.auth_providers_json or [])
                    if "phone" not in providers:
                        providers.append("phone")
                    row.phone_number = phone_number
                    if display_name and display_name.strip():
                        row.display_name = display_name.strip()
                    row.auth_providers_json = providers
                    row.updated_at = now
                    row.last_login_at = now

                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
                return self._map_user_row(row)

    async def create_otp_challenge(
        self,
        *,
        challenge_id: str,
        phone_number: str,
        code_hash: str,
        expires_at: datetime,
        max_per_window: int = 5,
        window_seconds: int = 300,
    ) -> str:
        now = utcnow()
        window_start = now - timedelta(seconds=window_seconds)
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                recent_cnt = int(
                    (
                        await session.execute(
                            select(func.count())
                            .select_from(OtpChallengeRow)
                            .where(
                                OtpChallengeRow.phone_number == phone_number,
                                OtpChallengeRow.created_at >= window_start,
                            )
                        )
                    ).scalar_one()
                )
                if recent_cnt >= max_per_window:
                    raise ValidationError(
                        "Too many OTP requests for this phone number; please wait a few minutes"
                    )

                await session.execute(
                    update(OtpChallengeRow)
                    .where(
                        OtpChallengeRow.phone_number == phone_number,
                        OtpChallengeRow.consumed_at.is_(None),
                    )
                    .values(consumed_at=now)
                )

                session.add(
                    OtpChallengeRow(
                        challenge_id=challenge_id,
                        phone_number=phone_number,
                        code_hash=code_hash,
                        attempts=0,
                        expires_at=expires_at,
                        consumed_at=None,
                        created_at=now,
                    )
                )
                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
        return challenge_id

    async def verify_otp_challenge(
        self,
        *,
        challenge_id: str,
        phone_number: str,
        expected_hash: str,
        max_attempts: int = 5,
    ) -> None:
        now = utcnow()
        async with self._write_lock_if_sqlite_standalone():
            async with self._session() as session:
                stmt = select(OtpChallengeRow).where(OtpChallengeRow.challenge_id == challenge_id)
                if self.is_postgres:
                    stmt = stmt.with_for_update()
                row = (await session.execute(stmt)).scalar_one_or_none()
                if row is None or row.phone_number != phone_number:
                    raise ValidationError("Invalid or unknown OTP challenge")
                if row.consumed_at is not None:
                    raise ValidationError("OTP challenge has already been used or superseded")
                if self._ensure_utc(row.expires_at) <= now:
                    row.consumed_at = now
                    await session.flush()
                    if _CURRENT_SESSION.get() is None:
                        await session.commit()
                    raise ValidationError("OTP code has expired; please request a new one")
                if row.attempts >= max_attempts:
                    row.consumed_at = now
                    await session.flush()
                    if _CURRENT_SESSION.get() is None:
                        await session.commit()
                    raise ValidationError("Maximum OTP verification attempts exceeded")

                if not hmac.compare_digest(row.code_hash, expected_hash):
                    row.attempts += 1
                    if row.attempts >= max_attempts:
                        row.consumed_at = now
                    await session.flush()
                    if _CURRENT_SESSION.get() is None:
                        await session.commit()
                    raise ValidationError("Incorrect OTP verification code")

                row.consumed_at = now
                await session.flush()
                if _CURRENT_SESSION.get() is None:
                    await session.commit()
