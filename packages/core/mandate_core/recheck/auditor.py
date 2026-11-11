from __future__ import annotations

import asyncio

from mandate_core.domain.models import (
    AuditVerdict,
    CaseSnapshot,
    Finding,
    FindingSeverity,
    Mandate,
)
from mandate_core.ports import LLM


async def run_advisory_audit(
    *,
    llm: LLM | None,
    mandate: Mandate,
    snapshot: CaseSnapshot,
    untrusted_product_text: str,
    timeout_seconds: float = 5.0,
) -> list[Finding]:
    """
    Run advisory AI Auditor with strict fail-escalation semantics:
    - Can only emit INFO, WARN ('flag'), or BLOCK ('block'); can NEVER approve.
    - Timeouts or errors escalate to WARN ('flag'), never 'ok'.
    """
    if llm is None:
        return []

    try:
        verdict: AuditVerdict = await asyncio.wait_for(
            llm.audit_snapshot(
                mandate=mandate,
                snapshot=snapshot,
                untrusted_product_text=untrusted_product_text,
            ),
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return [
            Finding(
                code="AI_AUDITOR_TIMEOUT_OR_ERROR",
                severity=FindingSeverity.WARN,
                source="ai_auditor",
                message=f"AI Auditor unavailable ({type(exc).__name__}); escalated to flag",
                explanation="Flagged: AI Auditor timed out or errored; deterministic rules still apply.",
            )
        ]

    if verdict.verdict == "ok":
        return [
            Finding(
                code="AI_AUDITOR_OK",
                severity=FindingSeverity.INFO,
                source="ai_auditor",
                message="AI Auditor observed no semantic anomalies or prompt injections",
                explanation="Advisory AI check noted no anomalies.",
                evidence={"reasons": verdict.reasons},
            )
        ]

    severity = FindingSeverity.BLOCK if verdict.verdict == "block" else FindingSeverity.WARN
    reason_text = "; ".join(verdict.reasons) if verdict.reasons else "AI Auditor raised an alert"
    return [
        Finding(
            code=f"AI_AUDITOR_{verdict.verdict.upper()}",
            severity=severity,
            source="ai_auditor",
            message=reason_text,
            explanation=f"AI Auditor ({verdict.verdict}): {reason_text}",
            evidence={"reasons": verdict.reasons},
        )
    ]
