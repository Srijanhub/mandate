from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from mandate_core.ledger import compute_agent_trust_score

from adapters.partner_elastic import serialize_ledger_docs
from apps.api.auth import require_user_auth
from apps.api.dependencies import AppContainer, get_container
from apps.api.schemas import (
    AgentTrustScore,
    ElasticSearchResponse,
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


@router.get("/search", response_model=ElasticSearchResponse)
async def search_ledger(
    query: str = "",
    limit: int = 20,
    container: AppContainer = Depends(get_container),
) -> ElasticSearchResponse:
    """Elastic search over audit ledger entries (with deterministic fallback)."""
    fallback_docs: list[tuple[str, dict[str, Any]]] | None = None
    if not container.elastic.is_live:
        entries = await container.store.iter_all_ledger()
        fallback_docs = serialize_ledger_docs(entries)
    res = await container.elastic.search(
        "ledger",
        query=query,
        fields=["event_type^3", "case_id^2", "mandate_id^2", "actor", "payload_json"],
        limit=max(1, min(limit, 100)),
        fallback_docs=fallback_docs,
    )
    return ElasticSearchResponse.model_validate(res)


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
