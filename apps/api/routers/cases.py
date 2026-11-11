from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from mandate_core.domain.errors import NotFoundError
from mandate_core.domain.models import CaseState, Proposal
from mandate_core.merger import diff
from mandate_core.recheck import Checkpoint
from mandate_core.workflows import build_proposal_from_product
from pydantic import BaseModel, Field

from apps.api.dependencies import AppContainer, get_container

router = APIRouter(prefix="/cases", tags=["Cases"])


class ProposeCaseRequest(BaseModel):
    mandate_id: str
    product_id: str
    quantity: int = Field(default=1, ge=1, le=50)
    rationale: str = ""
    lock_immediately: bool = False
    # Optional tampered proposal overrides for red-team / unit boundary tests
    override_unit_price_amount: str | None = None
    override_currency: str | None = None
    override_seller_id: str | None = None
    override_payee_id: str | None = None


class HoldRequest(BaseModel):
    duration_seconds: int = Field(default=900, ge=10, le=86400)
    actor: str = "user"


class CancelRequest(BaseModel):
    reason: str = "Cancelled by user"
    actor: str = "user"


class AuthorizeRequest(BaseModel):
    existing_order_id: str | None = None
    actor: str = "user"


@router.post("/propose", status_code=201)
async def propose_case(
    body: ProposeCaseRequest,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    mandate = await container.store.get_mandate(body.mandate_id)
    if mandate is None:
        raise NotFoundError(f"Mandate {body.mandate_id} not found")
    product = await container.catalog.get(body.product_id)
    if product is None:
        raise NotFoundError(f"Product {body.product_id} not found")

    prop: Proposal = build_proposal_from_product(
        mandate=mandate, product=product, quantity=body.quantity, rationale=body.rationale
    )
    if body.override_unit_price_amount is not None:
        from mandate_core.domain.models import Money

        cur = body.override_currency or product.price.currency
        unit_p = Money.of(body.override_unit_price_amount, cur)
        prop.claimed_unit_price = unit_p
        prop.claimed_total = unit_p * body.quantity
    if body.override_seller_id is not None:
        prop.claimed_seller_id = body.override_seller_id
    if body.override_payee_id is not None:
        prop.claimed_payee_id = body.override_payee_id

    case = await container.orchestrator.submit_proposal(prop, actor="shopping-agent")
    if body.lock_immediately and case.state == CaseState.PROPOSED:
        case = await container.orchestrator.lock_cart(case.case_id, actor="user")
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/lock")
async def lock_case_cart(
    case_id: str,
    actor: str = "user",
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    case = await container.orchestrator.lock_cart(case_id, actor=actor)
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/approve")
async def approve_case(
    case_id: str,
    actor: str = "user",
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    case = await container.orchestrator.approve_and_capture(case_id, actor=actor)
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/approve-only")
async def approve_case_only(
    case_id: str,
    actor: str = "user",
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    case = await container.orchestrator.approve(case_id, actor=actor)
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/authorize-only")
async def authorize_case_only(
    case_id: str,
    body: AuthorizeRequest | None = None,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    req = body or AuthorizeRequest()
    case = await container.orchestrator.authorize(
        case_id, existing_order_id=req.existing_order_id, actor=req.actor
    )
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/capture-only")
async def capture_case_only(
    case_id: str,
    actor: str = "orchestrator",
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    case = await container.orchestrator.capture(case_id, actor=actor)
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/hold")
async def hold_case(
    case_id: str,
    body: HoldRequest | None = None,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    req = body or HoldRequest()
    case = await container.orchestrator.hold_case(
        case_id, duration_seconds=req.duration_seconds, actor=req.actor
    )
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/resume")
async def resume_case(
    case_id: str,
    actor: str = "user",
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    case = await container.orchestrator.resume_case(case_id, actor=actor)
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/cancel")
async def cancel_case(
    case_id: str,
    body: CancelRequest | None = None,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    req = body or CancelRequest()
    case = await container.orchestrator.cancel(case_id, reason=req.reason, actor=req.actor)
    return {"case": case.model_dump(mode="json")}


@router.post("/{case_id}/recheck")
async def recheck_case(
    case_id: str,
    actor: str = "user",
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    case = await container.orchestrator.recheck_case(
        case_id, checkpoint=Checkpoint.C7_BACKGROUND_SWEEP, actor=actor
    )
    return {"case": case.model_dump(mode="json")}


@router.get("")
async def list_cases(
    mandate_id: str | None = None,
    state: CaseState | None = None,
    limit: int = 50,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    rows = await container.store.list_cases(mandate_id=mandate_id, state=state, limit=limit)
    return {"cases": [c.model_dump(mode="json") for c in rows]}


@router.get("/{case_id}")
async def get_case(
    case_id: str,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    case = await container.store.get_case(case_id)
    if case is None:
        raise NotFoundError(f"Case {case_id} not found")
    return {"case": case.model_dump(mode="json")}


@router.get("/{case_id}/why")
async def explain_case(
    case_id: str,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    return await container.orchestrator.explain_case(case_id)


@router.get("/{case_id}/snapshots")
async def list_case_snapshots(
    case_id: str,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    snaps = await container.store.list_snapshots(case_id)
    return {"snapshots": [s.model_dump(mode="json") for s in snaps]}


@router.get("/{case_id}/diff")
async def diff_case_snapshots(
    case_id: str,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    snaps = await container.store.list_snapshots(case_id)
    if len(snaps) < 2:
        return {"case_id": case_id, "diff": [], "snapshots_count": len(snaps)}
    findings = diff(snaps[0], snaps[-1])
    return {
        "case_id": case_id,
        "before": snaps[0].model_dump(mode="json"),
        "after": snaps[-1].model_dump(mode="json"),
        "diff": [f.model_dump(mode="json") for f in findings],
    }
