from __future__ import annotations

import asyncio
from typing import Any

from mandate_core.domain.models import Money, Product


def _map_channel3_product(raw: Any) -> Product:
    """Translate Channel3 SDK product response into Core Product without leaking SDK schema."""
    get_attr = (
        (lambda k, d=None: raw.get(k, d))
        if isinstance(raw, dict)
        else (lambda k, d=None: getattr(raw, k, d))
    )

    product_id = str(get_attr("id", "") or get_attr("product_id", ""))
    title = str(get_attr("title", "") or get_attr("name", "Untitled Item"))
    description = str(get_attr("description", "") or "")
    brand = str(get_attr("brand", "") or "Channel3 Merchant")
    url = get_attr("url", None)

    price_obj = get_attr("price", None)
    if isinstance(price_obj, dict):
        raw_amount = price_obj.get("price", price_obj.get("amount", "0.00"))
        currency = str(price_obj.get("currency", "USD"))
    elif price_obj is not None:
        raw_amount = getattr(price_obj, "price", getattr(price_obj, "amount", "0.00"))
        currency = str(getattr(price_obj, "currency", "USD"))
    else:
        raw_amount = "0.00"
        currency = "USD"

    offers = get_attr("offers", None) or []
    first_offer = offers[0] if offers else None
    seller_name = brand
    if isinstance(first_offer, dict):
        seller_name = str(first_offer.get("merchant_name", brand))
        in_stock = bool(first_offer.get("in_stock", True))
    elif first_offer is not None:
        seller_name = str(getattr(first_offer, "merchant_name", brand))
        in_stock = bool(getattr(first_offer, "in_stock", True))
    else:
        in_stock = bool(get_attr("availability", "in_stock") != "out_of_stock")

    categories = get_attr("categories", None) or []
    cat = str(categories[0]) if categories else str(get_attr("category", "general"))

    return Product(
        product_id=product_id,
        title=title,
        description=description,
        price=Money.of(str(raw_amount), currency),
        seller_id=f"ch3:{seller_name.lower().replace(' ', '-')}",
        seller_name=seller_name,
        seller_verified=True,
        payee_id=f"PAYEE-{seller_name.upper().replace(' ', '-')[:20]}",
        category=cat,
        in_stock=in_stock,
        estimated_delivery_days=3,
        url=str(url) if url else None,
        metadata={"source": "channel3"},
    )


class Channel3Catalog:
    """Catalog adapter backed by channel3-sdk (sponsor integration)."""

    def __init__(self, *, api_key: str | None = None, client: Any = None) -> None:
        if client is not None:
            self._client = client
        else:
            from channel3_sdk import Channel3

            self._client = Channel3(api_key=api_key) if api_key else Channel3()
        self._cache: dict[str, Product] = {}

    async def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[Product]:
        ch3_filters: dict[str, Any] = {}
        if filters and filters.get("category_ids"):
            ch3_filters["category_ids"] = filters["category_ids"]

        def _call() -> Any:
            return self._client.products.search(
                query=query, filters=ch3_filters or None, limit=limit
            )

        res = await asyncio.to_thread(_call)
        raw_items = res if isinstance(res, list) else getattr(res, "products", None) or getattr(res, "data", [])
        mapped = [_map_channel3_product(item) for item in raw_items]
        for p in mapped:
            self._cache[p.product_id] = p
        return mapped[:limit]

    async def get(self, product_id: str) -> Product | None:
        if product_id in self._cache:
            return self._cache[product_id]
        get_fn = getattr(self._client.products, "get", None)
        if callable(get_fn):
            raw = await asyncio.to_thread(get_fn, product_id)
            if raw is not None:
                p = _map_channel3_product(raw)
                self._cache[p.product_id] = p
                return p
        return None
