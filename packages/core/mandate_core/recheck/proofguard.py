from __future__ import annotations

from mandate_core.domain.models import (
    CaseSnapshot,
    ConflictCode,
    Finding,
    FindingSeverity,
    Mandate,
    PaymentEvidence,
)
from mandate_core.merger import explain_finding_code
from mandate_core.rules import RuleContext, evaluate_rules


class ProofGuardResult:
    def __init__(self, verified: bool, findings: list[Finding], summary: str) -> None:
        self.verified = verified
        self.findings = findings
        self.summary = summary


def verify_post_capture_proof(
    *,
    mandate: Mandate,
    approved_snapshot: CaseSnapshot | None,
    captured_snapshot: CaseSnapshot,
    paypal_evidence: PaymentEvidence,
) -> ProofGuardResult:
    """
    Checkpoint C6 (ProofGuard): compare what PayPal actually captured against what was approved
    and verify all deterministic mandate rules on the final settled evidence.
    """
    findings: list[Finding] = []

    if paypal_evidence.status.upper() not in {"COMPLETED", "CAPTURED"}:
        findings.append(
            Finding(
                code="CAPTURE_NOT_COMPLETED",
                severity=FindingSeverity.BLOCK,
                source="proofguard",
                message=f"PayPal capture status is {paypal_evidence.status}",
                explanation=f"Flagged: PayPal reported status '{paypal_evidence.status}' instead of COMPLETED.",
                evidence={"status": paypal_evidence.status, "capture_id": paypal_evidence.capture_id},
            )
        )

    if approved_snapshot is not None:
        if paypal_evidence.amount.currency != approved_snapshot.total_amount.currency:
            findings.append(
                Finding(
                    code=ConflictCode.CURRENCY_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="proofguard",
                    message="Captured currency differs from approved snapshot",
                    explanation=explain_finding_code(
                        ConflictCode.CURRENCY_MISMATCH.value,
                        expected=approved_snapshot.total_amount.currency,
                        actual=paypal_evidence.amount.currency,
                    ),
                )
            )
        elif paypal_evidence.amount != approved_snapshot.total_amount:
            findings.append(
                Finding(
                    code=ConflictCode.AMOUNT_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="proofguard",
                    message="Captured amount differs from approved total",
                    explanation=explain_finding_code(
                        ConflictCode.AMOUNT_MISMATCH.value,
                        expected=approved_snapshot.total_amount.to_str(),
                        actual=paypal_evidence.amount.to_str(),
                    ),
                    evidence={
                        "approved": str(approved_snapshot.total_amount.amount),
                        "captured": str(paypal_evidence.amount.amount),
                    },
                )
            )

        if paypal_evidence.payee_id and paypal_evidence.payee_id != approved_snapshot.payee_id:
            findings.append(
                Finding(
                    code=ConflictCode.PAYEE_MISMATCH.value,
                    severity=FindingSeverity.BLOCK,
                    source="proofguard",
                    message="Captured payee differs from approved payee",
                    explanation=explain_finding_code(
                        ConflictCode.PAYEE_MISMATCH.value,
                        expected=approved_snapshot.payee_id,
                        actual=paypal_evidence.payee_id,
                    ),
                )
            )

    policy_decision = evaluate_rules(RuleContext(mandate=mandate, snapshot=captured_snapshot))
    findings.extend(policy_decision.findings)

    failures = [f for f in findings if f.severity == FindingSeverity.BLOCK]
    if failures:
        summary = "ProofGuard FLAGGED: " + "; ".join(f.explanation for f in failures)
        return ProofGuardResult(verified=False, findings=findings, summary=summary)

    return ProofGuardResult(
        verified=True,
        findings=findings,
        summary=(
            f"ProofGuard VERIFIED: captured {paypal_evidence.amount.to_str()} "
            f"to payee {captured_snapshot.payee_id} matches approved mandate snapshot."
        ),
    )
