from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field

from mandate_core.domain.errors import ValidationError
from mandate_core.domain.models import (
    AuditVerdict,
    CaseSnapshot,
    FindingSeverity,
    Mandate,
    MandateStatus,
    Money,
    Product,
    Proposal,
    utcnow,
)
from mandate_core.merger import build_snapshot
from mandate_core.ports import LLM, Catalog
from mandate_core.rules import RuleContext, evaluate_rules

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY"}
INJECTION_MARKERS = (
    "ignore previous",
    "system override",
    "/approve",
    "/confirm",
    "/revoke",
    "bypass policy",
    "disregard mandate",
)


class CompiledMandateSchema(BaseModel):
    max_total_amount: str
    currency: str = "USD"
    max_spend_per_day_amount: str | None = None
    max_spend_per_week_amount: str | None = None
    max_transactions: int = Field(default=3, ge=1, le=100)
    require_verified_seller: bool = True
    allowed_sellers: list[str] = Field(default_factory=list)
    blocked_sellers: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    blocked_keywords: list[str] = Field(default_factory=list)
    deliver_within_days: int | None = None
    expires_in_hours: int = Field(default=24, ge=1, le=720)


def sanitize_untrusted_text(raw: str) -> str:
    """Neutralize leading slash commands & mark product text strictly as untrusted data."""
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("/"):
            lines.append(f"[untrusted-text] {stripped}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _deterministic_compile_dict(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if len(cleaned) < 3:
        raise ValidationError("Mandate prompt is too short")

    lower = cleaned.lower()
    currency = "USD"
    amount_str: str | None = None

    sym_m = re.search(r"([$€£₹¥])\s*(\d+(?:\.\d{1,3})?)", cleaned)
    if sym_m:
        currency = CURRENCY_SYMBOLS.get(sym_m.group(1), "USD")
        amount_str = sym_m.group(2)
    else:
        code_m = re.search(r"\b([A-Z]{3})\s*(\d+(?:\.\d{1,3})?)\b", cleaned) or re.search(
            r"\b(\d+(?:\.\d{1,3})?)\s*([A-Z]{3})\b", cleaned
        )
        if code_m:
            g1, g2 = code_m.group(1), code_m.group(2)
            if g1.isalpha():
                currency, amount_str = g1, g2
            else:
                amount_str, currency = g1, g2
        else:
            bare_m = re.search(
                r"\b(?:under|max|maximum|at\s+most|up\s+to|cap|limit|budget(?:\s+of)?)\s+(\d+(?:\.\d{1,2})?)\b",
                lower,
            )
            if bare_m:
                amount_str = bare_m.group(1)

    if not amount_str:
        raise ValidationError(
            "Mandate prompt must specify an explicit spending limit (e.g., 'under $60')"
        )

    opt_out_verified = bool(
        re.search(r"\b(?:any\s+seller|any\s+merchant|unverified\s+ok)\b", lower)
    )
    blocked_keywords: list[str] = []
    for m in re.finditer(
        r"\b(?:no|excluding|block|without)\s+([a-zA-Z0-9 -]{2,30}?)(?:,|\.|\band\b|$)",
        cleaned,
        flags=re.IGNORECASE,
    ):
        phrase = m.group(1).strip().lower()
        if phrase and not phrase.startswith("more than"):
            blocked_keywords.append(phrase)

    allowed_categories: list[str] = []
    for cat in ("gifts", "electronics", "home", "books", "fashion"):
        if cat in lower or (cat.rstrip("s") in lower):
            allowed_categories.append(cat)

    deliver_within_days: int | None = None
    day_m = re.search(r"\b(?:within|in)\s+(\d{1,2})\s+days?\b", lower)
    if day_m:
        deliver_within_days = int(day_m.group(1))
    elif "arriving friday" in lower or "by friday" in lower:
        now = utcnow()
        delta = (4 - now.weekday()) % 7
        deliver_within_days = max(1, delta or 1)

    max_tx = 3
    tx_m = re.search(r"\b(?:up\s+to|max)\s+(\d{1,2})\s+(?:orders?|transactions?)\b", lower)
    if tx_m:
        max_tx = int(tx_m.group(1))

    return {
        "max_total_amount": amount_str,
        "currency": currency,
        "max_transactions": max_tx,
        "require_verified_seller": not opt_out_verified,
        "allowed_categories": allowed_categories,
        "blocked_keywords": blocked_keywords,
        "deliver_within_days": deliver_within_days,
        "expires_in_hours": 24,
    }


async def compile_mandate_from_text(
    text: str,
    *,
    owner_id: str = "user-1",
    llm: LLM | None = None,
) -> Mandate:
    """
    Compile natural-language spending constraints into a DRAFT Mandate.
    Retries LLM once on schema error, hard-fails or uses deterministic extractor;
    always requires explicit /confirm before status becomes ACTIVE.
    """
    raw_dict: dict[str, Any] | None = None
    if llm is not None:
        for attempt in range(2):
            try:
                candidate = await llm.compile_mandate(text)
                validated = CompiledMandateSchema.model_validate(candidate)
                raw_dict = validated.model_dump()
                break
            except Exception as exc:
                if attempt == 1:
                    # Fallback to deterministic extractor only if LLM failed both tries,
                    # and still enforce explicit monetary limit!
                    raw_dict = _deterministic_compile_dict(text)
                    if not raw_dict:
                        raise ValidationError(f"Failed to compile mandate: {exc}") from exc

    if raw_dict is None:
        raw_dict = _deterministic_compile_dict(text)

    parsed = CompiledMandateSchema.model_validate(raw_dict)
    max_total = Money.of(parsed.max_total_amount, parsed.currency)
    if max_total.amount <= 0:
        raise ValidationError("Mandate max_total must be positive")

    now = utcnow()
    deliver_by = (
        now + timedelta(days=parsed.deliver_within_days)
        if parsed.deliver_within_days is not None
        else None
    )
    expires_at = now + timedelta(hours=parsed.expires_in_hours)

    return Mandate(
        owner_id=owner_id,
        domain="shopping",
        intent_text=text.strip(),
        max_total=max_total,
        max_spend_per_day=(
            Money.of(parsed.max_spend_per_day_amount, parsed.currency)
            if parsed.max_spend_per_day_amount
            else None
        ),
        max_spend_per_week=(
            Money.of(parsed.max_spend_per_week_amount, parsed.currency)
            if parsed.max_spend_per_week_amount
            else None
        ),
        max_transactions=parsed.max_transactions,
        allowed_sellers=parsed.allowed_sellers,
        blocked_sellers=parsed.blocked_sellers,
        require_verified_seller=parsed.require_verified_seller,
        allowed_categories=parsed.allowed_categories,
        blocked_keywords=parsed.blocked_keywords,
        deliver_by=deliver_by,
        expires_at=expires_at,
        status=MandateStatus.DRAFT,
    )


class RankedOption(BaseModel):
    product: Product
    deterministic_score: float
    reason: str
    sanitized_description: str


async def search_and_ask_preference(
    *,
    mandate: Mandate,
    query: str,
    catalog: Catalog,
    llm: LLM | None = None,
    limit: int = 5,
) -> list[RankedOption]:
    """
    Shopping agent workflow (search_products only, NO PayPal tools):
      1. Search catalog.
      2. Pre-filter candidates through deterministic Policy Engine.
      3. Score deterministically + ask LLM to rank/explain ONLY among candidate IDs
         (validates LLM output IDs are a strict subset of input candidate IDs).
    """
    raw_products = await catalog.search(
        query,
        filters={"verified_only": mandate.require_verified_seller},
        limit=20,
    )

    eligible: list[tuple[Product, float]] = []
    for p in raw_products:
        prop = Proposal(
            mandate_id=mandate.mandate_id,
            product_id=p.product_id,
            title=p.title,
            quantity=1,
            claimed_unit_price=p.price,
            claimed_total=p.price,
            claimed_seller_id=p.seller_id,
            claimed_payee_id=p.payee_id,
            category=p.category,
        )
        snap, merger_findings = build_snapshot(
            case_id="prefilter",
            checkpoint="PREFILTER",
            mandate=mandate,
            proposal=prop,
            catalog_item=p,
        )
        if any(f.severity == FindingSeverity.BLOCK for f in merger_findings):
            continue

        # Temporarily evaluate rules treating mandate as ACTIVE during pre-filter if still drafting
        eval_mandate = (
            mandate.model_copy(update={"status": MandateStatus.ACTIVE})
            if mandate.status == MandateStatus.DRAFT
            else mandate
        )
        decision = evaluate_rules(RuleContext(mandate=eval_mandate, snapshot=snap))
        if not decision.allow:
            continue

        # Deterministic score: headroom under cap + faster delivery + verified bonus
        headroom = float((mandate.max_total.amount - p.price.amount) / mandate.max_total.amount)
        speed_bonus = max(0.0, (7 - p.estimated_delivery_days) * 0.05)
        verified_bonus = 0.25 if p.seller_verified else 0.0
        score = round(1.0 + headroom * 0.5 + speed_bonus + verified_bonus, 4)
        eligible.append((p, score))

    eligible.sort(key=lambda pair: (-pair[1], pair[0].price.amount))
    candidate_products = [p for p, _ in eligible[: max(limit, 8)]]
    by_id = {p.product_id: (p, sc) for p, sc in eligible}

    ranked: list[RankedOption] = []
    if llm is not None and candidate_products:
        try:
            llm_picks = await llm.rank_candidates(
                intent_text=mandate.intent_text,
                candidates=candidate_products,
                limit=limit,
            )
            seen: set[str] = set()
            for item in llm_picks:
                pid = str(item.get("product_id", ""))
                # CRITICAL INVARIANT: only accept IDs from candidate_products!
                if pid in by_id and pid not in seen:
                    seen.add(pid)
                    p, sc = by_id[pid]
                    ranked.append(
                        RankedOption(
                            product=p,
                            deterministic_score=sc,
                            reason=str(item.get("reason", "Matches your mandate criteria.")),
                            sanitized_description=sanitize_untrusted_text(p.description),
                        )
                    )
        except Exception:
            ranked = []

    if not ranked:
        for p, sc in eligible[:limit]:
            ranked.append(
                RankedOption(
                    product=p,
                    deterministic_score=sc,
                    reason=(
                        f"Within {mandate.max_total.to_str()} budget "
                        f"({p.price.to_str()}) from {p.seller_name}."
                    ),
                    sanitized_description=sanitize_untrusted_text(p.description),
                )
            )

    return ranked[:limit]


def build_proposal_from_product(
    *,
    mandate: Mandate,
    product: Product,
    quantity: int = 1,
    rationale: str = "",
) -> Proposal:
    """Shopping agent's second action (`propose_purchase`): builds Proposal and stops."""
    total = product.price * quantity
    return Proposal(
        mandate_id=mandate.mandate_id,
        agent_id="shopping-agent",
        product_id=product.product_id,
        title=product.title,
        quantity=quantity,
        claimed_unit_price=product.price,
        claimed_total=total,
        claimed_seller_id=product.seller_id,
        claimed_payee_id=product.payee_id,
        category=product.category,
        estimated_delivery_at=utcnow() + timedelta(days=product.estimated_delivery_days),
        rationale=rationale or f"Selected {product.title} at {total.to_str()}",
        raw_metadata={"sanitized_description": sanitize_untrusted_text(product.description)},
    )


def heuristic_injection_audit(untrusted_text: str, snapshot: CaseSnapshot) -> AuditVerdict:
    """Deterministic fallback scanner for prompt injection patterns in product descriptions."""
    lower = f"{untrusted_text} {snapshot.title}".lower()
    hits = [m for m in INJECTION_MARKERS if m in lower]
    if hits:
        return AuditVerdict(
            verdict="block",
            reasons=[f"Prompt-injection marker detected in untrusted product text: {hits[0]!r}"],
        )
    return AuditVerdict(verdict="ok", reasons=[])


SHOPPING_AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_products",
        "description": "Search catalog products matching user query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords"},
                "limit": {"type": "integer", "description": "Max results (up to 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "propose_purchase",
        "description": "Submit a Proposal object for a chosen product_id. Cannot pay or capture funds.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "quantity": {"type": "integer"},
                "rationale": {"type": "string"},
            },
            "required": ["product_id", "rationale"],
        },
    },
]


async def run_shopping_agent(
    *,
    mandate: Mandate,
    query: str,
    catalog: Catalog,
    orchestrator: Any,
    llm: LLM | None = None,
) -> dict[str, Any]:
    """
    Execute the 2-tool Shopping Agent (search_products + propose_purchase ONLY).
    Product descriptions are sanitized and treated strictly as untrusted data.
    Never accesses PayPal tools.
    """
    proposed_cases: list[dict[str, Any]] = []
    tool_trace: list[dict[str, Any]] = []

    async def _search_products(search_query: str, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 10))
        options = await search_and_ask_preference(
            mandate=mandate,
            query=search_query,
            catalog=catalog,
            llm=None,
            limit=safe_limit,
        )
        results = [
            {
                "product_id": o.product.product_id,
                "title": o.product.title,
                "price": o.product.price.to_str(),
                "seller_name": o.product.seller_name,
                "seller_verified": o.product.seller_verified,
                "category": o.product.category,
                "untrusted_description": o.sanitized_description[:240],
                "score": o.deterministic_score,
            }
            for o in options
        ]
        tool_trace.append({"tool": "search_products", "query": search_query, "count": len(results)})
        return results

    async def _propose_purchase(
        product_id: str, quantity: int = 1, rationale: str = ""
    ) -> dict[str, Any]:
        product = await catalog.get(product_id)
        if product is None:
            return {"error": f"Unknown product_id {product_id!r}"}
        qty = max(1, int(quantity))
        prop = build_proposal_from_product(
            mandate=mandate,
            product=product,
            quantity=qty,
            rationale=rationale or f"Agent proposed {product.title}",
        )
        case = await orchestrator.submit_proposal(prop, actor="shopping-agent")
        summary = {"case_id": case.case_id, "state": case.state.value, "product_id": product_id}
        proposed_cases.append(summary)
        tool_trace.append({"tool": "propose_purchase", **summary})
        return summary

    runner = getattr(llm, "run_shopping_tools", None) if llm is not None else None
    if callable(runner):
        try:
            await runner(
                query=query,
                mandate=mandate,
                search_fn=_search_products,
                propose_fn=_propose_purchase,
            )
        except Exception:
            pass

    if not proposed_cases:
        # Deterministic 2-tool execution fallback
        candidates = await _search_products(query, 5)
        if candidates:
            top = candidates[0]
            await _propose_purchase(
                top["product_id"],
                1,
                f"Top policy-compliant option matching '{query}' ({top['price']}).",
            )

    case_obj = (
        await orchestrator.store.get_case(proposed_cases[0]["case_id"])
        if proposed_cases
        else None
    )
    return {
        "mandate_id": mandate.mandate_id,
        "tools_exposed": [t["name"] for t in SHOPPING_AGENT_TOOLS],
        "tool_trace": tool_trace,
        "case": case_obj.model_dump(mode="json") if case_obj else None,
    }

