from __future__ import annotations

import json
from typing import Any

from mandate_core.domain.models import AuditVerdict, CaseSnapshot, Mandate, Product
from mandate_core.workflows.shopping import (
    heuristic_injection_audit,
    sanitize_untrusted_text,
)


class GroqLLM:
    """
    Backup Groq adapter (`llama-3.3-70b-versatile`, temperature=0, JSON mode)
    behind the exact same Core LLM port.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        client: Any = None,
    ) -> None:
        self.model = model
        if client is not None:
            self.client = client
        else:
            from groq import AsyncGroq

            self.client = AsyncGroq(api_key=api_key)

    async def compile_mandate(self, text: str) -> dict[str, Any]:
        resp = await self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return JSON with max_total_amount, currency, max_transactions, "
                        "require_verified_seller, allowed_categories, blocked_keywords, "
                        "deliver_within_days, expires_in_hours."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        return json.loads(resp.choices[0].message.content or "{}")

    async def rank_candidates(
        self,
        *,
        intent_text: str,
        candidates: list[Product],
        limit: int = 5,
    ) -> list[dict[str, str]]:
        payload = [
            {"product_id": p.product_id, "title": p.title, "price": p.price.to_str()}
            for p in candidates
        ]
        resp = await self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Return JSON {'picks': [{'product_id': ..., 'reason': ...}]} using only given IDs.",
                },
                {"role": "user", "content": json.dumps({"intent": intent_text, "candidates": payload, "limit": limit})},
            ],
        )
        data = json.loads(resp.choices[0].message.content or '{"picks": []}')
        return list(data.get("picks", []))[:limit]

    async def audit_snapshot(
        self,
        *,
        mandate: Mandate,
        snapshot: CaseSnapshot,
        untrusted_product_text: str,
    ) -> AuditVerdict:
        heuristic = heuristic_injection_audit(untrusted_product_text, snapshot)
        if heuristic.verdict == "block":
            return heuristic

        resp = await self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Return strict JSON {'verdict': 'ok'|'flag'|'block', 'reasons': [...]}",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "intent": mandate.intent_text,
                            "title": snapshot.title,
                            "untrusted_description": sanitize_untrusted_text(untrusted_product_text)[:400],
                        }
                    ),
                },
            ],
        )
        return AuditVerdict.model_validate_json(resp.choices[0].message.content or '{"verdict": "flag", "reasons": []}')
