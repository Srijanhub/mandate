from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from mandate_core.ledger import compute_agent_trust_score

from apps.api.dependencies import AppContainer, get_container

router = APIRouter(prefix="/ledger", tags=["Ledger"])


@router.get("")
async def list_ledger(
    case_id: str | None = None,
    mandate_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    startRow: int | None = None,
    endRow: int | None = None,
    sortDir: str = "desc",
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """AG Grid Server-Side Row Model compatible ledger query endpoint."""
    effective_offset = startRow if startRow is not None else offset
    effective_limit = (
        max(1, min(endRow - startRow, 500))
        if (startRow is not None and endRow is not None)
        else max(1, min(limit, 500))
    )
    entries, total = await container.store.list_ledger(
        case_id=case_id,
        mandate_id=mandate_id,
        event_type=event_type,
        limit=effective_limit,
        offset=effective_offset,
        sort_dir="asc" if sortDir.lower() == "asc" else "desc",
    )
    return {
        "rows": [e.model_dump(mode="json") for e in entries],
        "total_count": total,
        "lastRow": total,
    }


@router.get("/verify")
async def verify_ledger(
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    return await container.orchestrator.verify_ledger()


@router.get("/trust-score")
async def agent_trust_score(
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    entries = await container.store.iter_all_ledger()
    return compute_agent_trust_score(entries).model_dump(mode="json")
