from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from mandate_core.domain.models import (
    Case,
    CaseSnapshot,
    CaseState,
    LedgerEntry,
    Mandate,
    RecheckJob,
)


@runtime_checkable
class StateStore(Protocol):
    """Persistence port for Mandate Core (implemented by SQLAlchemy Postgres/SQLite adapter)."""

    @asynccontextmanager
    def atomic(self) -> AsyncIterator[None]: ...

    async def save_mandate(self, mandate: Mandate) -> Mandate: ...

    async def get_mandate(self, mandate_id: str, *, version: int | None = None) -> Mandate | None: ...

    async def get_latest_mandate(self, *, owner_id: str | None = None) -> Mandate | None: ...

    async def get_active_mandate(self, *, owner_id: str | None = None) -> Mandate | None: ...

    async def list_mandates(self, *, owner_id: str | None = None, limit: int = 50) -> list[Mandate]: ...

    async def save_case(self, case: Case) -> Case: ...

    async def get_case(self, case_id: str, *, for_update: bool = False) -> Case | None: ...

    async def get_latest_case(self) -> Case | None: ...

    async def list_cases(
        self, *, mandate_id: str | None = None, state: CaseState | None = None, limit: int = 50
    ) -> list[Case]: ...

    async def list_open_cases(self) -> list[Case]: ...

    async def list_held_or_authorized_cases(self) -> list[Case]: ...

    async def save_snapshot(self, snapshot: CaseSnapshot) -> CaseSnapshot: ...

    async def get_snapshot(self, snapshot_id: str) -> CaseSnapshot | None: ...

    async def list_snapshots(self, case_id: str) -> list[CaseSnapshot]: ...

    async def append_ledger(
        self,
        *,
        case_id: str | None,
        mandate_id: str | None,
        actor: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> LedgerEntry: ...

    async def list_ledger(
        self,
        *,
        case_id: str | None = None,
        mandate_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
        sort_dir: str = "desc",
    ) -> tuple[list[LedgerEntry], int]: ...

    async def iter_all_ledger(self) -> list[LedgerEntry]: ...

    async def enqueue_recheck_job(self, job: RecheckJob) -> RecheckJob: ...

    async def claim_due_recheck_jobs(self, *, now: datetime, limit: int = 10) -> list[RecheckJob]: ...

    async def finish_recheck_job(
        self, job_id: str, *, status: str, error: str | None = None
    ) -> None: ...

    async def record_webhook_if_new(self, event_id: str, event_type: str, payload: dict[str, Any]) -> bool: ...
