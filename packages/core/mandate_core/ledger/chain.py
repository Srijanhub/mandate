from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

from mandate_core.domain.models import LedgerEntry

GENESIS_HASH = hashlib.sha256(b"MANDATE_LEDGER_GENESIS_V1").hexdigest()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        dt = obj if obj.tzinfo is not None else obj.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    raise TypeError(f"Object of type {type(obj).__name__} is not canonical-JSON serializable")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=_json_default)


def compute_entry_hash(
    *,
    seq: int,
    entry_id: str,
    case_id: str | None,
    mandate_id: str | None,
    actor: str,
    event_type: str,
    payload: dict[str, Any],
    prev_hash: str,
    created_at: datetime,
) -> str:
    dt = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    meta = {
        "v": 1,
        "seq": seq,
        "id": entry_id,
        "case_id": case_id,
        "mandate_id": mandate_id,
        "actor": actor,
        "event_type": event_type,
        "created_at": dt.astimezone(UTC).isoformat(),
    }
    preimage = f"{prev_hash}|{canonical_json(payload)}|{canonical_json(meta)}"
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


class LedgerVerificationResult(BaseModel):
    valid: bool
    total_entries: int
    verified_entries: int
    genesis_hash: str
    latest_hash: str | None
    first_broken_seq: int | None
    first_broken_id: str | None
    broken_reason: str | None


def verify_ledger_chain(entries: Iterable[LedgerEntry]) -> LedgerVerificationResult:
    expected_seq = 1
    expected_prev = GENESIS_HASH
    verified = 0
    total = 0
    latest_hash: str | None = None

    for entry in entries:
        total += 1
        if entry.seq != expected_seq:
            return LedgerVerificationResult(
                valid=False,
                total_entries=total,
                verified_entries=verified,
                genesis_hash=GENESIS_HASH,
                latest_hash=latest_hash,
                first_broken_seq=entry.seq,
                first_broken_id=entry.id,
                broken_reason=f"Sequence mismatch: expected seq={expected_seq}, got seq={entry.seq}",
            )

        if entry.prev_hash != expected_prev:
            return LedgerVerificationResult(
                valid=False,
                total_entries=total,
                verified_entries=verified,
                genesis_hash=GENESIS_HASH,
                latest_hash=latest_hash,
                first_broken_seq=entry.seq,
                first_broken_id=entry.id,
                broken_reason=f"prev_hash link broken at seq={entry.seq}",
            )

        recomputed = compute_entry_hash(
            seq=entry.seq,
            entry_id=entry.id,
            case_id=entry.case_id,
            mandate_id=entry.mandate_id,
            actor=entry.actor,
            event_type=entry.event_type,
            payload=entry.payload,
            prev_hash=entry.prev_hash,
            created_at=entry.created_at,
        )
        if recomputed != entry.hash:
            return LedgerVerificationResult(
                valid=False,
                total_entries=total,
                verified_entries=verified,
                genesis_hash=GENESIS_HASH,
                latest_hash=latest_hash,
                first_broken_seq=entry.seq,
                first_broken_id=entry.id,
                broken_reason=f"Hash mismatch at seq={entry.seq} (row tampered)",
            )

        expected_seq += 1
        expected_prev = entry.hash
        latest_hash = entry.hash
        verified += 1

    return LedgerVerificationResult(
        valid=True,
        total_entries=total,
        verified_entries=verified,
        genesis_hash=GENESIS_HASH,
        latest_hash=latest_hash,
        first_broken_seq=None,
        first_broken_id=None,
        broken_reason=None,
    )


class AgentTrustScore(BaseModel):
    trust_score_percent: float
    total_cases: int
    clean_verified_cases: int
    blocked_or_flagged_cases: int
    avg_time_to_verify_seconds: float | None
    total_ledger_entries: int


def compute_agent_trust_score(entries: Iterable[LedgerEntry]) -> AgentTrustScore:
    case_start: dict[str, datetime] = {}
    case_verified: dict[str, datetime] = {}
    blocked_or_flagged_cases: set[str] = set()
    all_cases: set[str] = set()
    total_entries = 0

    for e in entries:
        total_entries += 1
        if not e.case_id:
            continue
        all_cases.add(e.case_id)
        if e.case_id not in case_start:
            case_start[e.case_id] = e.created_at
        if e.event_type in {"CASE_VERIFIED", "PROOFGUARD_VERIFIED"}:
            case_verified[e.case_id] = e.created_at
        if e.event_type in {
            "CASE_BLOCKED",
            "CASE_FLAGGED",
            "PROOFGUARD_FLAGGED",
            "DRIFT_DETECTED",
            "ILLEGAL_TRANSITION_ATTEMPT",
        }:
            blocked_or_flagged_cases.add(e.case_id)

    total_cases = len(all_cases)
    clean_cases = len(set(case_verified.keys()) - blocked_or_flagged_cases)
    flagged_count = len(blocked_or_flagged_cases)

    durations: list[float] = []
    for cid, end_ts in case_verified.items():
        start_ts = case_start.get(cid)
        if start_ts is not None:
            durations.append(max(0.0, (end_ts - start_ts).total_seconds()))

    if total_cases == 0:
        trust_pct = 100.0
    else:
        trust_pct = round(((total_cases - flagged_count) / total_cases) * 100.0, 2)

    avg_verify = round(sum(durations) / len(durations), 3) if durations else None

    return AgentTrustScore(
        trust_score_percent=trust_pct,
        total_cases=total_cases,
        clean_verified_cases=clean_cases,
        blocked_or_flagged_cases=flagged_count,
        avg_time_to_verify_seconds=avg_verify,
        total_ledger_entries=total_entries,
    )
