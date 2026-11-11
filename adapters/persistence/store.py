from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mandate_core.domain.errors import IllegalTransitionError, PolicyBlockedError
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
from sqlalchemy import Select, event, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import (
    Base,
    CaseRow,
    LedgerEntryRow,
    MandateRow,
    RecheckJobRow,
    SnapshotRow,
    WebhookEventRow,
)

_CURRENT_SESSION: ContextVar[AsyncSession | None] = ContextVar("mandate_current_session", default=None)


def create_engine_and_sessionmaker(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    if database_url.startswith("sqlite"):
        if ":///" in database_url and not database_url.endswith(":memory:"):
            raw_path = database_url.split(":///", 1)[1]
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(database_url, echo=False)

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            cursor.close()
    else:
        engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


class SqlAlchemyStateStore:
    """
    Async SQLAlchemy StateStore supporting PostgreSQL (advisory lock + FOR UPDATE SKIP LOCKED)
    and SQLite (serialized async write lock) behind the Core StateStore protocol.
    """

    def __init__(self, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.engine = engine
        self.session_factory = session_factory
        self.is_postgres = engine.dialect.name == "postgresql"
        self._sqlite_write_lock = asyncio.Lock()

    async def init_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def atomic(self) -> AsyncIterator[None]:
        existing = _CURRENT_SESSION.get()
        if existing is not None:
            yield
            return

        if not self.is_postgres:
            async with self._sqlite_write_lock:
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
            return

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

    async def get_latest_case(self) -> Case | None:
        async with self._session() as session:
            stmt = select(CaseRow).order_by(CaseRow.updated_at.desc()).limit(1)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return Case.model_validate(row.data_json) if row else None

    async def list_cases(
        self, *, mandate_id: str | None = None, state: CaseState | None = None, limit: int = 50
    ) -> list[Case]:
        async with self._session() as session:
            stmt = select(CaseRow).order_by(CaseRow.updated_at.desc()).limit(limit)
            if mandate_id:
                stmt = stmt.where(CaseRow.mandate_id == mandate_id)
            if state:
                stmt = stmt.where(CaseRow.state == state.value)
            rows = (await session.execute(stmt)).scalars().all()
            return [Case.model_validate(r.data_json) for r in rows]

    async def list_open_cases(self) -> list[Case]:
        open_values = [s.value for s in OPEN_CASE_STATES]
        async with self._session() as session:
            stmt = select(CaseRow).where(CaseRow.state.in_(open_values)).order_by(CaseRow.created_at.asc())
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

    async def list_snapshots(self, case_id: str) -> list[CaseSnapshot]:
        async with self._session() as session:
            stmt = (
                select(SnapshotRow)
                .where(SnapshotRow.case_id == case_id)
                .order_by(SnapshotRow.created_at.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [CaseSnapshot.model_validate(r.data_json) for r in rows]

    # ------------------------------------------------------------------
    # Hash-Chained Ledger (Advisory Lock on Postgres)
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
        async with self._session() as session:
            if self.is_postgres:
                await session.execute(text("SELECT pg_advisory_xact_lock(73918273)"))

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

    async def list_ledger(
        self,
        *,
        case_id: str | None = None,
        mandate_id: str | None = None,
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
            if event_type:
                base = base.where(LedgerEntryRow.event_type == event_type)
                cnt_q = cnt_q.where(LedgerEntryRow.event_type == event_type)

            order_col = LedgerEntryRow.seq.asc() if sort_dir == "asc" else LedgerEntryRow.seq.desc()
            rows = (
                await session.execute(base.order_by(order_col).limit(limit).offset(offset))
            ).scalars().all()
            total = int((await session.execute(cnt_q)).scalar_one())
            return [self._map_ledger_row(r) for r in rows], total

    async def iter_all_ledger(self) -> list[LedgerEntry]:
        async with self._session() as session:
            rows = (
                await session.execute(select(LedgerEntryRow).order_by(LedgerEntryRow.seq.asc()))
            ).scalars().all()
            return [self._map_ledger_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Recheck Job Queue (SELECT ... FOR UPDATE SKIP LOCKED on Postgres)
    # ------------------------------------------------------------------

    async def enqueue_recheck_job(self, job: RecheckJob) -> RecheckJob:
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

    async def record_webhook_if_new(
        self, event_id: str, event_type: str, payload: dict[str, Any]
    ) -> bool:
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
                return bool(res.rowcount == 1)

            existing = await session.get(WebhookEventRow, event_id)
            if existing is not None:
                return False
            session.add(
                WebhookEventRow(
                    event_id=event_id,
                    event_type=event_type,
                    payload=payload,
                    received_at=utcnow(),
                )
            )
            await session.flush()
            return True
