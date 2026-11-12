from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from mandate_core.domain.errors import NotFoundError
from mandate_core.domain.models import Mandate, Money
from mandate_core.workflows import compile_mandate_from_text
from pydantic import BaseModel, Field

from apps.api.auth import AuthIdentity, get_optional_identity, require_user_auth
from apps.api.dependencies import AppContainer, get_container
from apps.api.schemas import (
    BryntumEvent,
    BryntumResource,
    BryntumTimelineResponse,
    MandateDraftResponse,
    MandateListResponse,
    MandateResponse,
    RevokeAllResponse,
)

router = APIRouter(prefix="/mandates", tags=["Mandates"], dependencies=[Depends(require_user_auth)])


class CompileMandateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    owner_id: str = "user-1"


class AmendMandateRequest(BaseModel):
    max_total_amount: str | None = None
    currency: str | None = None
    max_spend_per_day_amount: str | None = None
    max_spend_per_week_amount: str | None = None
    max_transactions: int | None = None
    require_verified_seller: bool | None = None
    allowed_sellers: list[str] | None = None
    blocked_sellers: list[str] | None = None
    allowed_categories: list[str] | None = None
    blocked_keywords: list[str] | None = None
    deliver_by: datetime | None = None
    expires_at: datetime | None = None
    actor: str = "user"


class RevokeRequest(BaseModel):
    reason: str = "Kill switch triggered by user"
    actor: str = "user"


@router.post("/compile", status_code=201, response_model=MandateDraftResponse)
async def compile_mandate(
    body: CompileMandateRequest,
    identity: AuthIdentity | None = Depends(get_optional_identity),
    container: AppContainer = Depends(get_container),
) -> MandateDraftResponse:
    effective_owner = (
        identity.user_id
        if (identity and identity.user_id and body.owner_id == "user-1")
        else body.owner_id
    )
    draft: Mandate = await compile_mandate_from_text(
        body.prompt, owner_id=effective_owner, llm=container.llm
    )
    saved = await container.orchestrator.create_mandate_draft(draft, actor=effective_owner)
    return MandateDraftResponse(mandate=saved, needs_confirm=True)


@router.post("/{mandate_id}/confirm", response_model=MandateResponse)
async def confirm_mandate(
    mandate_id: str,
    actor: str = "user",
    container: AppContainer = Depends(get_container),
) -> MandateResponse:
    confirmed = await container.orchestrator.confirm_mandate(mandate_id, actor=actor)
    return MandateResponse(mandate=confirmed)


@router.post("/{mandate_id}/amend", response_model=MandateDraftResponse)
async def amend_mandate(
    mandate_id: str,
    body: AmendMandateRequest,
    container: AppContainer = Depends(get_container),
) -> MandateDraftResponse:
    current = await container.store.get_mandate(mandate_id)
    if current is None:
        raise NotFoundError(f"Mandate {mandate_id} not found")
    cur_code = body.currency or current.max_total.currency
    updates: dict[str, Any] = {}
    if body.max_total_amount is not None:
        updates["max_total"] = Money.of(body.max_total_amount, cur_code)
    if body.max_spend_per_day_amount is not None:
        updates["max_spend_per_day"] = Money.of(body.max_spend_per_day_amount, cur_code)
    if body.max_spend_per_week_amount is not None:
        updates["max_spend_per_week"] = Money.of(body.max_spend_per_week_amount, cur_code)
    for key in (
        "max_transactions",
        "require_verified_seller",
        "allowed_sellers",
        "blocked_sellers",
        "allowed_categories",
        "blocked_keywords",
        "deliver_by",
        "expires_at",
    ):
        val = getattr(body, key)
        if val is not None:
            updates[key] = val

    amended = await container.orchestrator.amend_mandate(
        mandate_id, updates=updates, actor=body.actor
    )
    return MandateDraftResponse(mandate=amended, needs_confirm=True)


@router.post("/revoke", response_model=RevokeAllResponse)
async def revoke_all_mandates(
    body: RevokeRequest | None = None,
    container: AppContainer = Depends(get_container),
) -> RevokeAllResponse:
    req = body or RevokeRequest()
    res = await container.orchestrator.revoke_all(reason=req.reason, actor=req.actor)
    return RevokeAllResponse(**res)


@router.get("", response_model=MandateListResponse)
async def list_mandates(
    owner_id: str | None = None,
    limit: int = 50,
    container: AppContainer = Depends(get_container),
) -> MandateListResponse:
    rows = await container.store.list_mandates(owner_id=owner_id, limit=limit)
    return MandateListResponse(mandates=rows)


@router.get("/schedule", response_model=BryntumTimelineResponse)
async def mandates_schedule(
    owner_id: str | None = None,
    limit: int = 50,
    container: AppContainer = Depends(get_container),
) -> BryntumTimelineResponse:
    """Bryntum Calendar/Scheduler compatible feed of mandate validity and delivery windows."""
    rows = await container.store.list_mandates(owner_id=owner_id, limit=max(1, min(limit, 200)))
    resources: list[BryntumResource] = []
    events: list[BryntumEvent] = []
    seen_owners: set[str] = set()
    for m in rows:
        if m.owner_id not in seen_owners:
            seen_owners.add(m.owner_id)
            resources.append(
                BryntumResource(id=m.owner_id, name=f"Owner {m.owner_id}", role="owner")
            )
        end_dt = m.deliver_by or m.expires_at
        if end_dt < m.created_at:
            end_dt = m.created_at
        events.append(
            BryntumEvent(
                id=f"{m.mandate_id}-v{m.version}",
                resourceId=m.owner_id,
                name=f"[{m.status.value}] {m.max_total.to_str()} — {m.intent_text[:60]}",
                startDate=m.created_at.isoformat(),
                endDate=end_dt.isoformat(),
                status=m.status.value,
                eventColor="green" if m.status.value == "ACTIVE" else "slate",
                meta={
                    "mandate_id": m.mandate_id,
                    "version": m.version,
                    "expires_at": m.expires_at.isoformat(),
                },
            )
        )
    return BryntumTimelineResponse(resources=resources, events=events)


@router.get("/{mandate_id}", response_model=MandateResponse)
async def get_mandate(
    mandate_id: str,
    version: int | None = None,
    container: AppContainer = Depends(get_container),
) -> MandateResponse:
    m = await container.store.get_mandate(mandate_id, version=version)
    if m is None:
        raise NotFoundError(f"Mandate {mandate_id} not found")
    return MandateResponse(mandate=m)
