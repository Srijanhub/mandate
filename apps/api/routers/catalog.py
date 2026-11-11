from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from mandate_core.domain.errors import NotFoundError, ValidationError
from mandate_core.workflows import (
    build_proposal_from_product,
    run_shopping_agent,
    search_and_ask_preference,
)
from pydantic import BaseModel

from adapters.catalog_mock import MockCatalog
from apps.api.auth import require_admin_auth, require_user_auth
from apps.api.dependencies import AppContainer, get_container
from apps.api.schemas import (
    CaseResponse,
    CatalogSearchResponse,
    ProductResponse,
    RankedOptionResponse,
    ShoppingAgentResponse,
    ShoppingOptionsResponse,
)

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


class ShoppingAgentRequest(BaseModel):
    mandate_id: str
    query: str


@router.get("/catalog/search", response_model=CatalogSearchResponse)
async def search_catalog(
    query: str = "",
    verified_only: bool = False,
    category: str | None = None,
    limit: int = 20,
    container: AppContainer = Depends(get_container),
) -> CatalogSearchResponse:
    filters: dict[str, Any] = {"verified_only": verified_only}
    if category:
        filters["category"] = category
    products = await container.catalog.search(query, filters=filters, limit=limit)
    return CatalogSearchResponse(products=products)


@router.get("/catalog/{product_id}", response_model=ProductResponse)
async def get_catalog_item(
    product_id: str,
    container: AppContainer = Depends(get_container),
) -> ProductResponse:
    item = await container.catalog.get(product_id)
    if item is None:
        raise NotFoundError(f"Product {product_id} not found")
    return ProductResponse(product=item)


@router.post(
    "/shopping/options",
    response_model=ShoppingOptionsResponse,
    dependencies=[Depends(require_user_auth)],
)
async def shopping_options(
    body: SearchOptionsRequest,
    container: AppContainer = Depends(get_container),
) -> ShoppingOptionsResponse:
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
    return ShoppingOptionsResponse(
        mandate_id=mandate.mandate_id,
        options=[
            RankedOptionResponse(
                index=idx + 1,
                product=o.product,
                deterministic_score=o.deterministic_score,
                reason=o.reason,
                sanitized_description=o.sanitized_description,
            )
            for idx, o in enumerate(options)
        ],
    )


@router.post(
    "/shopping/agent",
    status_code=201,
    response_model=ShoppingAgentResponse,
    dependencies=[Depends(require_user_auth)],
)
async def shopping_agent_propose(
    body: ShoppingAgentRequest,
    container: AppContainer = Depends(get_container),
) -> ShoppingAgentResponse:
    """Invoke the 2-tool Shopping Agent (search_products + propose_purchase ONLY; zero PayPal tools)."""
    mandate = await container.store.get_mandate(body.mandate_id)
    if mandate is None:
        raise NotFoundError(f"Mandate {body.mandate_id} not found")
    res = await run_shopping_agent(
        mandate=mandate,
        query=body.query,
        catalog=container.catalog,
        orchestrator=container.orchestrator,
        llm=container.llm,
    )
    return ShoppingAgentResponse.model_validate(res)


@router.post(
    "/shopping/pick",
    status_code=201,
    response_model=CaseResponse,
    dependencies=[Depends(require_user_auth)],
)
async def shopping_pick(
    body: PickOptionRequest,
    container: AppContainer = Depends(get_container),
) -> CaseResponse:
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
    return CaseResponse(case=case)


@router.post(
    "/admin/catalog/{product_id}/price",
    response_model=ProductResponse,
    dependencies=[Depends(require_admin_auth)],
)
async def admin_bump_price(
    product_id: str,
    body: BumpPriceRequest,
    container: AppContainer = Depends(get_container),
) -> ProductResponse:
    if not isinstance(container.catalog, MockCatalog):
        raise ValidationError("Price mutation endpoint is only available on MockCatalog")
    try:
        updated = container.catalog.bump_price(product_id, body.new_amount)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    return ProductResponse(product=updated)


@router.post(
    "/admin/catalog/{product_id}/stock",
    response_model=ProductResponse,
    dependencies=[Depends(require_admin_auth)],
)
async def admin_toggle_stock(
    product_id: str,
    body: StockToggleRequest,
    container: AppContainer = Depends(get_container),
) -> ProductResponse:
    if not isinstance(container.catalog, MockCatalog):
        raise ValidationError("Stock mutation endpoint is only available on MockCatalog")
    try:
        updated = container.catalog.set_stock(product_id, body.in_stock)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    return ProductResponse(product=updated)
