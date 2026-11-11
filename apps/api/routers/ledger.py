from __future__ import annotations

from fastapi import APIRouter, Depends
from mandate_core.ledger import compute_agent_trust_score

from apps.api.auth import require_user_auth
from apps.api.dependencies import AppContainer, get_container
from apps.api.schemas import (
    AgentTrustScore,
    LedgerListResponse,
    LedgerVerificationResult,
)

router = APIRouter(prefix="/ledger", tags=["Ledger"], dependencies=[Depends(require_user_auth)])


@router.get("", response_model=LedgerListResponse)
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
) -> LedgerListResponse:
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
    return LedgerListResponse(rows=entries, total_count=total, lastRow=total)


@router.get("/verify", response_model=LedgerVerificationResult)
async def verify_ledger(
    container: AppContainer = Depends(get_container),
) -> LedgerVerificationResult:
    data = await container.orchestrator.verify_ledger()
    return LedgerVerificationResult.model_validate(data)


@router.get("/trust-score", response_model=AgentTrustScore)
async def agent_trust_score(
    container: AppContainer = Depends(get_container),
) -> AgentTrustScore:
    entries = await container.store.iter_all_ledger()
    return compute_agent_trust_score(entries)
