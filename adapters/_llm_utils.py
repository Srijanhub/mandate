from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from mandate_core.domain.models import AuditVerdict
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from adapters.errors import redact_secrets

logger = logging.getLogger("mandate.llm")

T = TypeVar("T")

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", flags=re.DOTALL | re.IGNORECASE)
_AMOUNT_KEYS = ("max_total_amount", "max_spend_per_day_amount", "max_spend_per_week_amount")


class LLMTransientError(RuntimeError):
    """Sanitized exception raised after bounded retries exhaust on transient LLM errors."""

    def __init__(self, message: str, *, error_code: str = "LLM_TRANSIENT_ERROR") -> None:
        super().__init__(redact_secrets(message))
        self.error_code = error_code


def _extract_status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    if resp is not None:
        sc = getattr(resp, "status_code", None)
        if isinstance(sc, int):
            return sc
    return None


def classify_llm_error(exc: BaseException) -> tuple[bool, str]:
    """Classify an LLM exception into (is_retryable, stable_error_code)."""
    if isinstance(exc, TimeoutError):
        return True, "LLM_TIMEOUT"
    cls_name = type(exc).__name__.lower()
    if "timeout" in cls_name:
        return True, "LLM_TIMEOUT"

    status = _extract_status_code(exc)
    if status == 429 or "ratelimit" in cls_name:
        return True, "LLM_RATE_LIMITED"
    if status in {502, 503, 504}:
        return True, "LLM_SERVICE_UNAVAILABLE"
    if status in {401, 403}:
        return False, "LLM_AUTH_ERROR"

    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return True, "LLM_RATE_LIMITED"
    if "503" in msg or "service unavailable" in msg or "502" in msg or "504" in msg:
        return True, "LLM_SERVICE_UNAVAILABLE"
    if "timed out" in msg or "timeout" in msg:
        return True, "LLM_TIMEOUT"

    if isinstance(exc, (json.JSONDecodeError, PydanticValidationError)):
        return False, "LLM_INVALID_JSON"

    return False, f"LLM_{type(exc).__name__.upper()}"


async def call_with_retry(
    op: Callable[[], Awaitable[T]],
    *,
    provider: str,
    max_retries: int = 2,
    base_delay: float = 0.2,
    max_delay: float = 2.0,
    timeout_seconds: float | None = None,
) -> T:
    """
    Execute an async LLM call with bounded exponential backoff on 429 / 503 / timeouts.
    All warning logs pass through `redact_secrets`.
    """
    attempts = max(1, max_retries + 1)
    for attempt in range(attempts):
        try:
            coro = op()
            if timeout_seconds is not None:
                return await asyncio.wait_for(coro, timeout=timeout_seconds)
            return await coro
        except Exception as exc:
            retryable, error_code = classify_llm_error(exc)
            safe_detail = redact_secrets(str(exc))[:240]
            logger.warning(
                "LLM call failed provider=%s code=%s attempt=%d/%d detail=%s",
                provider,
                error_code,
                attempt + 1,
                attempts,
                safe_detail,
            )
            if retryable and attempt < attempts - 1:
                delay = min(max_delay, base_delay * (2**attempt))
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            if retryable:
                raise LLMTransientError(
                    f"{provider} exhausted retries ({error_code}): {safe_detail}",
                    error_code=error_code,
                ) from exc
            raise
    raise LLMTransientError(f"{provider} failed unexpectedly", error_code="LLM_UNKNOWN")


class ReceiptSummaryResponse(BaseModel):
    summary: str


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


def parse_receipt_narrative(raw: str) -> str | None:
    """Parse JSON {'summary': ...} receipt summary, returning None on malformed output."""
    try:
        cleaned = strip_json_fences(raw)
        parsed = ReceiptSummaryResponse.model_validate_json(cleaned)
        text = parsed.summary.strip()
        return text or None
    except (json.JSONDecodeError, PydanticValidationError, TypeError, ValueError):
        return None


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
