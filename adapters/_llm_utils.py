from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from mandate_core.domain.models import AuditVerdict
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", flags=re.DOTALL | re.IGNORECASE)
_AMOUNT_KEYS = ("max_total_amount", "max_spend_per_day_amount", "max_spend_per_week_amount")


class RankingItem(BaseModel):
    product_id: str
    reason: str


class RankingResponse(BaseModel):
    picks: list[RankingItem]


def strip_json_fences(raw: str) -> str:
    """Remove optional ```json ... ``` markdown wrappers around model JSON output."""
    text = raw.strip()
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text


def coerce_amount_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce numeric spend-limit fields into strings expected by CompiledMandateSchema."""
    for key in _AMOUNT_KEYS:
        if key in parsed and parsed[key] is not None and not isinstance(parsed[key], str):
            parsed[key] = str(parsed[key])
    return parsed


def parse_mandate_json(raw: str) -> dict[str, Any]:
    """Parse compiled mandate JSON or raise ValueError for upstream retry/fallback."""
    cleaned = strip_json_fences(raw)
    parsed = json.loads(cleaned or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object for compiled mandate")
    return coerce_amount_fields(dict(parsed))


def parse_ranking_picks(raw: str, *, limit: int) -> list[dict[str, str]]:
    """Parse candidate ranking JSON, returning [] (fail-closed) on malformed output."""
    try:
        cleaned = strip_json_fences(raw)
        parsed = RankingResponse.model_validate_json(cleaned or '{"picks": []}')
        return [{"product_id": p.product_id, "reason": p.reason} for p in parsed.picks[:limit]]
    except (json.JSONDecodeError, PydanticValidationError, TypeError, ValueError):
        return []


def parse_audit_verdict(raw: str) -> AuditVerdict:
    """Parse AI auditor JSON, failing closed to verdict='flag' on malformed output."""
    try:
        cleaned = strip_json_fences(raw)
        return AuditVerdict.model_validate_json(cleaned)
    except (json.JSONDecodeError, PydanticValidationError, TypeError, ValueError):
        return AuditVerdict(verdict="flag", reasons=["Malformed LLM audit output"])


def safe_int(val: Any, *, default: int, min_value: int = 1, max_value: int = 100) -> int:
    """Safely convert tool integer arguments with strict bounds."""
    try:
        if isinstance(val, bool):
            return default
        parsed = int(val)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(parsed, max_value))


def parse_tool_args(raw_args: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Parse dict or JSON-string tool arguments without crashing the agent loop."""
    if raw_args is None:
        return {}, None
    if isinstance(raw_args, dict):
        return dict(raw_args), None
    if isinstance(raw_args, str):
        try:
            loaded = json.loads(strip_json_fences(raw_args) or "{}")
        except json.JSONDecodeError as exc:
            return None, f"Invalid JSON tool arguments: {exc.msg}"
        if not isinstance(loaded, dict):
            return None, "Tool arguments must decode to a JSON object"
        return dict(loaded), None
    return None, "Unsupported tool arguments type"


def extract_openai_choice_message(data: dict[str, Any]) -> dict[str, Any]:
    """Validate OpenAI-style chat completion response envelope."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Gateway response contained no choices")
    first = choices[0]
    if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
        raise ValueError("Gateway response choice contained invalid message")
    return first["message"]


async def dispatch_shopping_tool(
    name: str,
    raw_args: Any,
    *,
    default_query: str,
    search_fn: Callable[[str, int], Awaitable[list[dict[str, Any]]]],
    propose_fn: Callable[[str, int, str], Awaitable[dict[str, Any]]],
) -> Any:
    """Safely validate and execute only the 2 permitted shopping tools."""
    args, err = parse_tool_args(raw_args)
    if err is not None or args is None:
        return {"error": err or "Invalid tool arguments"}
    if name == "search_products":
        return await search_fn(
            str(args.get("query", default_query)),
            safe_int(args.get("limit"), default=5, min_value=1, max_value=50),
        )
    if name == "propose_purchase":
        return await propose_fn(
            str(args.get("product_id", "")),
            safe_int(args.get("quantity"), default=1, min_value=1, max_value=20),
            str(args.get("rationale", "")),
        )
    return {"error": f"Tool {name!r} is not permitted"}
