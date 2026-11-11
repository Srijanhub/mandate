from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from mandate_core.domain.errors import NotFoundError, ValidationError
from mandate_core.workflows import build_proposal_from_product, search_and_ask_preference
from pydantic import BaseModel

from adapters.catalog_mock import MockCatalog
from apps.api.dependencies import AppContainer, get_container

router = APIRouter(tags=["Catalog & Shopping"])


class SearchOptionsRequest(BaseModel):
    mandate_id: str
    query: str
    limit: int = 5


class PickOptionRequest(BaseModel):
    mandate_id: str
    product_id: str
    quantity: int = 1
    rationale: str = ""


class BumpPriceRequest(BaseModel):
    new_amount: str


class StockToggleRequest(BaseModel):
    in_stock: bool


@router.get("/catalog/search")
async def search_catalog(
    query: str = "",
    verified_only: bool = False,
    category: str | None = None,
    limit: int = 20,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    filters: dict[str, Any] = {"verified_only": verified_only}
    if category:
        filters["category"] = category
    products = await container.catalog.search(query, filters=filters, limit=limit)
    return {"products": [p.model_dump(mode="json") for p in products]}


@router.get("/catalog/{product_id}")
async def get_catalog_item(
    product_id: str,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    item = await container.catalog.get(product_id)
    if item is None:
        raise NotFoundError(f"Product {product_id} not found")
    return {"product": item.model_dump(mode="json")}


@router.post("/shopping/options")
async def shopping_options(
    body: SearchOptionsRequest,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    mandate = await container.store.get_mandate(body.mandate_id)
    if mandate is None:
        raise NotFoundError(f"Mandate {body.mandate_id} not found")
    options = await search_and_ask_preference(
        mandate=mandate,
        query=body.query,
        catalog=container.catalog,
        llm=container.llm,
        limit=body.limit,
    )
    container.last_options = options
    return {
        "mandate_id": mandate.mandate_id,
        "options": [
            {
                "index": idx + 1,
                "product": o.product.model_dump(mode="json"),
                "deterministic_score": o.deterministic_score,
                "reason": o.reason,
                "sanitized_description": o.sanitized_description,
            }
            for idx, o in enumerate(options)
        ],
    }


@router.post("/shopping/pick", status_code=201)
async def shopping_pick(
    body: PickOptionRequest,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    mandate = await container.store.get_mandate(body.mandate_id)
    if mandate is None:
        raise NotFoundError(f"Mandate {body.mandate_id} not found")
    product = await container.catalog.get(body.product_id)
    if product is None:
        raise NotFoundError(f"Product {body.product_id} not found")

    prop = build_proposal_from_product(
        mandate=mandate, product=product, quantity=body.quantity, rationale=body.rationale
    )
    case = await container.orchestrator.submit_proposal(prop, actor="shopping-agent")
    if case.state.value == "PROPOSED":
        case = await container.orchestrator.lock_cart(case.case_id, actor="user")
    return {"case": case.model_dump(mode="json")}


@router.post("/admin/catalog/{product_id}/price")
async def admin_bump_price(
    product_id: str,
    body: BumpPriceRequest,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    if not isinstance(container.catalog, MockCatalog):
        raise ValidationError("Price mutation endpoint is only available on MockCatalog")
    try:
        updated = container.catalog.bump_price(product_id, body.new_amount)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    return {"product": updated.model_dump(mode="json")}


@router.post("/admin/catalog/{product_id}/stock")
async def admin_toggle_stock(
    product_id: str,
    body: StockToggleRequest,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    if not isinstance(container.catalog, MockCatalog):
        raise ValidationError("Stock mutation endpoint is only available on MockCatalog")
    try:
        updated = container.catalog.set_stock(product_id, body.in_stock)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    return {"product": updated.model_dump(mode="json")}
