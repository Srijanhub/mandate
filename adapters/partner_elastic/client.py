from __future__ import annotations

import json
import re
from typing import Any

import httpx

from adapters.errors import ExternalServiceError


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def _score_doc(query: str, doc: dict[str, Any], fields: list[str]) -> float:
    q_clean = query.strip().lower()
    if not q_clean:
        return 1.0
    q_tokens = _tokenize(q_clean)
    score = 0.0
    for raw_field in fields:
        field_name, *boost_parts = raw_field.split("^", 1)
        boost = float(boost_parts[0]) if boost_parts and boost_parts[0].replace(".", "", 1).isdigit() else 1.0
        val = str(doc.get(field_name, "") or "").lower()
        if not val:
            continue
        overlap = len(q_tokens & _tokenize(val))
        if overlap:
            score += overlap * boost
        if q_clean in val:
            score += 2.5 * boost
    return score


def serialize_catalog_docs(products: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    """Convert Core Product models into Elastic-indexable (id, doc) pairs."""
    return [
        (
            p.product_id,
            {
                "product_id": p.product_id,
                "title": p.title,
                "description": p.description,
                "category": p.category,
                "seller_id": p.seller_id,
                "seller_name": p.seller_name,
                "seller_verified": p.seller_verified,
                "price": p.price.to_str(),
                "currency": p.price.currency,
                "in_stock": p.in_stock,
            },
        )
        for p in products
    ]


def serialize_ledger_docs(entries: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    """Convert Core LedgerEntry models into Elastic-indexable (id, doc) pairs."""
    return [
        (
            f"seq-{e.seq}",
            {
                "seq": e.seq,
                "event_type": e.event_type,
                "case_id": e.case_id or "",
                "mandate_id": e.mandate_id or "",
                "actor": e.actor,
                "payload_json": json.dumps(e.payload, default=str),
                "hash": e.hash,
                "created_at": e.created_at.isoformat(),
            },
        )
        for e in entries
    ]


class ElasticSearchAdapter:
    """
    Elasticsearch hybrid/text search adapter.
    Uses Elasticsearch REST API (_bulk, _search, _cluster/health) when ELASTIC_URL and
    ELASTIC_API_KEY are configured, and deterministic in-memory scored search otherwise.
    """

    def __init__(
        self,
        *,
        url: str = "",
        api_key: str = "",
        index_prefix: str = "mandate",
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url.strip().rstrip("/")
        self.api_key = api_key.strip()
        self.index_prefix = (index_prefix or "mandate").strip().lower()
        self.timeout = timeout
        self._transport = transport
        self._fallback_docs: dict[str, dict[str, dict[str, Any]]] = {}

    @property
    def is_live(self) -> bool:
        return bool(self.url and self.api_key)

    def _index_name(self, suffix: str) -> str:
        return f"{self.index_prefix}-{suffix}"

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        return {
            "Authorization": f"ApiKey {self.api_key}",
            "Content-Type": content_type,
            "Accept": "application/json",
        }

    async def probe(self) -> dict[str, Any]:
        """Check Elasticsearch cluster health without altering indices."""
        if not self.is_live:
            return {"configured": False, "ok": False, "mode": "deterministic_fallback"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                resp = await client.get(
                    f"{self.url}/_cluster/health",
                    headers=self._headers(),
                )
                if resp.status_code in (404, 410):
                    # Elastic Cloud Serverless returns 410 for /_cluster/health; root / returns cluster info.
                    resp = await client.get(
                        f"{self.url}/",
                        headers=self._headers(),
                    )
                return {
                    "configured": True,
                    "ok": resp.status_code < 400,
                    "status_code": resp.status_code,
                    "mode": "live",
                }
        except Exception as exc:
            return {"configured": True, "ok": False, "mode": "live", "error": str(exc)[:200]}

    async def bulk_index(
        self,
        index_suffix: str,
        docs: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Index documents into Elasticsearch or the local fallback store."""
        bucket = self._fallback_docs.setdefault(index_suffix, {})
        for doc_id, doc in docs:
            bucket[doc_id] = doc

        if not self.is_live or not docs:
            return {
                "mode": "deterministic_fallback",
                "index": self._index_name(index_suffix),
                "indexed": len(docs),
                "errors": False,
            }

        lines: list[str] = []
        index_name = self._index_name(index_suffix)
        for doc_id, doc in docs:
            lines.append(json.dumps({"index": {"_index": index_name, "_id": doc_id}}))
            lines.append(json.dumps(doc))
        ndjson = "\n".join(lines) + "\n"

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                resp = await client.post(
                    f"{self.url}/{index_name}/_bulk?refresh=wait_for",
                    headers=self._headers("application/x-ndjson"),
                    content=ndjson,
                )
        except httpx.HTTPError as exc:
            return {
                "mode": "live",
                "index": index_name,
                "indexed": 0,
                "errors": True,
                "error": str(exc)[:200],
            }
        if resp.status_code >= 400:
            return {
                "mode": "live",
                "index": index_name,
                "indexed": 0,
                "errors": True,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
        data = resp.json()
        return {
            "mode": "live",
            "index": index_name,
            "indexed": len(docs),
            "errors": bool(data.get("errors", False)),
        }

    async def search(
        self,
        index_suffix: str,
        *,
        query: str,
        fields: list[str],
        limit: int = 10,
        fallback_docs: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Run Elastic multi-match search or deterministic scored fallback search."""
        index_name = self._index_name(index_suffix)
        if self.is_live:
            body: dict[str, Any] = {
                "size": limit,
                "query": (
                    {"match_all": {}}
                    if not query.strip()
                    else {
                        "bool": {
                            "should": [
                                {
                                    "multi_match": {
                                        "query": query,
                                        "fields": fields,
                                        "fuzziness": "AUTO",
                                    }
                                },
                                {
                                    "multi_match": {
                                        "query": query,
                                        "fields": fields,
                                        "type": "phrase_prefix",
                                    }
                                },
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                ),
            }
            try:
                async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                    resp = await client.post(
                        f"{self.url}/{index_name}/_search",
                        headers=self._headers(),
                        json=body,
                    )
            except httpx.HTTPError as exc:
                if fallback_docs is None:
                    raise ExternalServiceError(f"Elastic search request failed: {exc}") from exc
            else:
                if resp.status_code < 400:
                    raw_hits = resp.json().get("hits", {}).get("hits", [])
                    hits = [
                        {
                            "id": str(h.get("_id", "")),
                            "score": float(h.get("_score") or 0.0),
                            "source": h.get("_source") or {},
                        }
                        for h in raw_hits[:limit]
                    ]
                    return {"mode": "live", "index": index_name, "total": len(hits), "hits": hits}
                if fallback_docs is None and resp.status_code not in {404}:
                    raise ExternalServiceError(
                        f"Elastic search failed (HTTP {resp.status_code})",
                        details={"index": index_name, "status_code": resp.status_code},
                    )

        pool = (
            list(fallback_docs)
            if fallback_docs is not None
            else list(self._fallback_docs.get(index_suffix, {}).items())
        )
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for doc_id, doc in pool:
            score = _score_doc(query, doc, fields)
            if score > 0 or not query.strip():
                scored.append((score, doc_id, doc))
        scored.sort(key=lambda item: (-item[0], item[1]))
        hits = [
            {"id": doc_id, "score": round(score, 3), "source": doc}
            for score, doc_id, doc in scored[:limit]
        ]
        return {
            "mode": "deterministic_fallback",
            "index": index_name,
            "total": len(hits),
            "hits": hits,
        }
