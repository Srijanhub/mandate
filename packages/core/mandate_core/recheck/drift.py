from __future__ import annotations

from mandate_core.domain.models import CaseSnapshot, Finding, FindingSeverity
from mandate_core.merger import diff


def detect_drift(
    approved_snapshot: CaseSnapshot | None,
    fresh_snapshot: CaseSnapshot,
) -> list[Finding]:
    """Compare fresh snapshot against user-approved snapshot; any difference flags drift."""
    if approved_snapshot is None:
        return []
    drift_findings = diff(approved_snapshot, fresh_snapshot)
    if not drift_findings:
        return [
            Finding(
                code="DRIFT_CHECK_CLEAN",
                severity=FindingSeverity.INFO,
                source="drift_detector",
                message="No drift detected since approval",
                explanation="Price, quantity, seller, payee, and stock match what you approved.",
            )
        ]
    return drift_findings
