from __future__ import annotations

import asyncio
import itertools
from typing import Any

from mandate_core.domain.models import Money, Product


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _map_channel3_product(raw: Any) -> Product:
    """Translate Channel3 SDK product response into Core Product without leaking SDK schema."""
    product_id = str(_attr(raw, "id", "") or _attr(raw, "product_id", ""))
    title = str(_attr(raw, "title", "") or _attr(raw, "name", "Untitled Item"))
    description = str(_attr(raw, "description", "") or "")

    brands = _attr(raw, "brands", None) or []
    first_brand = brands[0] if brands else None
    brand = str(
        _attr(first_brand, "name", "")
        or _attr(raw, "brand", "")
        or "Channel3 Merchant"
    )

    offers = _attr(raw, "offers", None) or []
    first_offer = offers[0] if offers else None
    url = _attr(raw, "url", None) or _attr(first_offer, "url", None)

    price_obj = _attr(raw, "price", None) or _attr(first_offer, "price", None)
    if price_obj is not None:
        raw_amount = _attr(price_obj, "price", None)
        if raw_amount is None:
            raw_amount = _attr(price_obj, "amount", "0.00")
        currency = str(_attr(price_obj, "currency", "USD") or "USD")
    else:
        raw_amount = "0.00"
        currency = "USD"

    seller_name = brand
    if first_offer is not None:
        seller_name = str(
            _attr(first_offer, "merchant_name", "")
            or _attr(first_offer, "domain", "")
            or brand
        )
        raw_in_stock = _attr(first_offer, "in_stock", None)
        if raw_in_stock is not None:
            in_stock = bool(raw_in_stock)
        else:
            avail = str(_attr(first_offer, "availability", "InStock"))
            in_stock = avail.lower() not in {"outofstock", "out_of_stock", "discontinued"}
    else:
        in_stock = bool(_attr(raw, "availability", "in_stock") != "out_of_stock")

    categories = _attr(raw, "categories", None) or []
    cat_obj = _attr(raw, "category", None)
    if categories:
        cat = str(categories[0])
    elif cat_obj is not None and not isinstance(cat_obj, str):
        cat = str(_attr(cat_obj, "slug", "") or _attr(cat_obj, "title", "general"))
    else:
        cat = str(cat_obj or "general")

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

        effective_query = query.strip()

        def _call() -> list[Any]:
            kwargs: dict[str, Any] = {"query": effective_query, "limit": limit}
            if ch3_filters:
                kwargs["filters"] = ch3_filters
            res = self._client.products.search(**kwargs)
            if isinstance(res, list):
                return res[:limit]
            products_attr = getattr(res, "products", None)
            if products_attr is not None:
                return list(products_attr)[:limit]
            data_attr = getattr(res, "data", None)
            if data_attr is not None:
                return list(data_attr)[:limit]
            return list(itertools.islice(res, limit))

        try:
            raw_items = await asyncio.to_thread(_call)
        except Exception:
            # Channel3's backend rejects an empty query when no filters/image/page_token are given;
            # return cached items instead of substituting a synthetic default query.
            if not effective_query:
                return list(self._cache.values())[:limit]
            raise
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
