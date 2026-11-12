from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from mandate_core.domain.errors import (
    IllegalTransitionError,
    NotFoundError,
    PaymentProviderError,
    PolicyBlockedError,
    ValidationError,
)
from mandate_core.domain.models import (
    Case,
    CaseSnapshot,
    CaseState,
    Decision,
    Finding,
    FindingSeverity,
    Mandate,
    MandateStatus,
    Money,
    PaymentEvidence,
    Product,
    Proposal,
    RecheckJob,
    utcnow,
)
from mandate_core.ledger import IntentReceipt, generate_intent_receipt, verify_ledger_chain
from mandate_core.merger import build_snapshot, diff
from mandate_core.ports import LLM, Catalog, Notifier, PaymentProvider
from mandate_core.recheck import (
    Checkpoint,
    ProofGuardResult,
    detect_drift,
    run_advisory_audit,
    verify_post_capture_proof,
)
from mandate_core.rules import RuleContext, evaluate_rules
from mandate_core.statemachine.store import StateStore
from mandate_core.statemachine.transitions import (
    OPEN_CASE_STATES,
    can_transition_case,
    can_transition_mandate,
)


class Orchestrator:
    """
    Core Mandate State Machine & Checkpoint Orchestrator.
    Every state mutation writes a tamper-evident ledger entry inside the same DB transaction.
    UI buttons and slash commands call these exact handlers.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        catalog: Catalog,
        payment: PaymentProvider,
        llm: LLM | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.payment = payment
        self.llm = llm
        self.notifier = notifier

    # ------------------------------------------------------------------
    # Internal helpers (must be invoked inside store.atomic() where mutating)
    # ------------------------------------------------------------------

    async def _transition_case(
        self,
        case: Case,
        target: CaseState,
        *,
        actor: str,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Case:
        if not can_transition_case(case.state, target):
            await self.store.append_ledger(
                case_id=case.case_id,
                mandate_id=case.mandate_id,
                actor=actor,
                event_type="ILLEGAL_TRANSITION_ATTEMPT",
                payload={"from": case.state.value, "to": target.value, **(payload or {})},
            )
            raise IllegalTransitionError(
                f"Illegal case transition from {case.state.value} to {target.value}",
                details={"case_id": case.case_id, "from": case.state.value, "to": target.value},
            )
        prev = case.state
        case.state = target
        case.updated_at = utcnow()
        await self.store.save_case(case)
        await self.store.append_ledger(
            case_id=case.case_id,
            mandate_id=case.mandate_id,
            actor=actor,
            event_type=event_type or f"CASE_{target.value}",
            payload={"from": prev.value, "to": target.value, **(payload or {})},
        )
        return case

    async def _notify(
        self, event: str, case_id: str | None, message: str, details: dict[str, Any] | None = None
    ) -> None:
        if self.notifier is not None:
            try:
                await self.notifier.notify(
                    event=event, case_id=case_id, message=message, details=details
                )
            except Exception:
                # Notifications never break core enforcement
                pass

    async def _run_recheck_pipeline(
        self,
        *,
        case: Case,
        mandate: Mandate,
        checkpoint: Checkpoint,
        catalog_item: Product | None,
        payment_evidence: PaymentEvidence | None,
        actor: str,
    ) -> tuple[CaseSnapshot, list[Finding], bool, bool]:
        """
        Execute Merger -> Drift Detector -> Policy Engine -> AI Auditor.
        Returns (snapshot, all_findings, blocked, drifted).
        """
        snapshot, merger_findings = build_snapshot(
            case_id=case.case_id,
            checkpoint=checkpoint.value,
            mandate=mandate,
            proposal=case.proposal,
            catalog_item=catalog_item,
            payment_evidence=payment_evidence,
        )
        await self.store.save_snapshot(snapshot)

        approved_snap: CaseSnapshot | None = None
        if case.approved_snapshot_id:
            approved_snap = await self.store.get_snapshot(case.approved_snapshot_id)

        drift_findings = detect_drift(approved_snap, snapshot)
        drifted = any(f.severity == FindingSeverity.BLOCK for f in drift_findings)

        policy_decision: Decision = evaluate_rules(
            RuleContext(mandate=mandate, snapshot=snapshot, now=utcnow())
        )
        untrusted_text = catalog_item.description if catalog_item else case.proposal.title
        ai_findings = await run_advisory_audit(
            llm=self.llm,
            mandate=mandate,
            snapshot=snapshot,
            untrusted_product_text=untrusted_text,
        )

        all_findings = [*merger_findings, *drift_findings, *policy_decision.findings, *ai_findings]
        blocked = any(f.severity == FindingSeverity.BLOCK for f in all_findings)

        case.latest_snapshot_id = snapshot.snapshot_id
        case.last_findings = all_findings
        case.updated_at = utcnow()
        await self.store.save_case(case)

        await self.store.append_ledger(
            case_id=case.case_id,
            mandate_id=mandate.mandate_id,
            actor=actor,
            event_type=f"CHECKPOINT_{checkpoint.value}",
            payload={
                "checkpoint": checkpoint.value,
                "snapshot_id": snapshot.snapshot_id,
                "blocked": blocked,
                "drifted": drifted,
                "finding_codes": [f.code for f in all_findings if f.severity != FindingSeverity.INFO],
            },
        )
        return snapshot, all_findings, blocked, drifted

    # ------------------------------------------------------------------
    # Mandate Lifecycle
    # ------------------------------------------------------------------

    async def create_mandate_draft(self, mandate: Mandate, *, actor: str = "user") -> Mandate:
        mandate.status = MandateStatus.DRAFT
        async with self.store.atomic():
            saved = await self.store.save_mandate(mandate)
            await self.store.append_ledger(
                case_id=None,
                mandate_id=saved.mandate_id,
                actor=actor,
                event_type="MANDATE_DRAFT_CREATED",
                payload={"version": saved.version, "max_total": saved.max_total.to_str()},
            )
        return saved

    async def confirm_mandate(self, mandate_id: str | None = None, *, actor: str = "user") -> Mandate:
        async with self.store.atomic():
            mandate = (
                await self.store.get_mandate(mandate_id)
                if mandate_id
                else await self.store.get_latest_mandate()
            )
            if mandate is None:
                raise NotFoundError("No mandate draft found to confirm")
            if not can_transition_mandate(mandate.status, MandateStatus.ACTIVE):
                await self.store.append_ledger(
                    case_id=None,
                    mandate_id=mandate.mandate_id,
                    actor=actor,
                    event_type="ILLEGAL_TRANSITION_ATTEMPT",
                    payload={"mandate_status": mandate.status.value, "target": "ACTIVE"},
                )
                raise IllegalTransitionError(
                    f"Cannot confirm mandate in status {mandate.status.value}"
                )
            mandate.status = MandateStatus.ACTIVE
            mandate.updated_at = utcnow()
            await self.store.save_mandate(mandate)
            await self.store.append_ledger(
                case_id=None,
                mandate_id=mandate.mandate_id,
                actor=actor,
                event_type="MANDATE_CONFIRMED",
                payload={"version": mandate.version, "intent": mandate.intent_text},
            )
            return mandate

    async def amend_mandate(
        self,
        mandate_id: str | None,
        *,
        updates: dict[str, Any],
        actor: str = "user",
    ) -> Mandate:
        async with self.store.atomic():
            current = (
                await self.store.get_mandate(mandate_id)
                if mandate_id
                else await self.store.get_latest_mandate()
            )
            if current is None:
                raise NotFoundError("Mandate not found")
            if current.status == MandateStatus.REVOKED:
                raise IllegalTransitionError("Cannot amend a REVOKED mandate")

            data = current.model_dump()
            data.update(updates)
            data["version"] = current.version + 1
            data["status"] = MandateStatus.DRAFT
            data["updated_at"] = utcnow()
            new_version = Mandate.model_validate(data)
            await self.store.save_mandate(new_version)
            await self.store.append_ledger(
                case_id=None,
                mandate_id=new_version.mandate_id,
                actor=actor,
                event_type="MANDATE_AMENDED",
                payload={"new_version": new_version.version, "updates": updates},
            )
            return new_version

    # ------------------------------------------------------------------
    # Shopping Case Lifecycle (C1..C8)
    # ------------------------------------------------------------------

    async def submit_proposal(self, proposal: Proposal, *, actor: str = "agent") -> Case:
        async with self.store.atomic():
            mandate = await self.store.get_mandate(proposal.mandate_id)
            if mandate is None:
                raise NotFoundError(f"Mandate {proposal.mandate_id} not found")

            catalog_item = await self.catalog.get(proposal.product_id)
            case = Case(
                mandate_id=mandate.mandate_id,
                mandate_version=mandate.version,
                state=CaseState.PROPOSED,
                proposal=proposal,
            )
            await self.store.save_case(case)
            await self.store.append_ledger(
                case_id=case.case_id,
                mandate_id=mandate.mandate_id,
                actor=actor,
                event_type="CASE_PROPOSED",
                payload={"product_id": proposal.product_id, "quantity": proposal.quantity},
            )

            _, all_findings, blocked, _ = await self._run_recheck_pipeline(
                case=case,
                mandate=mandate,
                checkpoint=Checkpoint.C1_PROPOSAL,
                catalog_item=catalog_item,
                payment_evidence=None,
                actor=actor,
            )
            if blocked:
                await self._transition_case(
                    case,
                    CaseState.BLOCKED,
                    actor="policy_engine",
                    payload={"reasons": [f.explanation for f in all_findings if f.severity == FindingSeverity.BLOCK]},
                )
            return case

    async def lock_cart(self, case_id: str, *, actor: str = "user") -> Case:
        async with self.store.atomic():
            case = await self.store.get_case(case_id, for_update=True)
            if case is None:
                raise NotFoundError(f"Case {case_id} not found")
            mandate = await self.store.get_mandate(case.mandate_id)
            if mandate is None:
                raise NotFoundError(f"Mandate {case.mandate_id} not found")

            await self._transition_case(case, CaseState.CART_LOCKED, actor=actor)
            catalog_item = await self.catalog.get(case.proposal.product_id)
            _, findings, blocked, _ = await self._run_recheck_pipeline(
                case=case,
                mandate=mandate,
                checkpoint=Checkpoint.C2_CART_LOCK,
                catalog_item=catalog_item,
                payment_evidence=None,
                actor="policy_engine",
            )
            if blocked:
                await self._transition_case(
                    case,
                    CaseState.BLOCKED,
                    actor="policy_engine",
                    payload={"reasons": [f.explanation for f in findings if f.severity == FindingSeverity.BLOCK]},
                )
                return case

            await self._transition_case(case, CaseState.CHECKED, actor="policy_engine")
            # C3 before showing approval card
            _, c3_findings, c3_blocked, _ = await self._run_recheck_pipeline(
                case=case,
                mandate=mandate,
                checkpoint=Checkpoint.C3_PRE_APPROVAL_CARD,
                catalog_item=catalog_item,
                payment_evidence=None,
                actor="policy_engine",
            )
            if c3_blocked:
                await self._transition_case(
                    case,
                    CaseState.BLOCKED,
                    actor="policy_engine",
                    payload={"reasons": [f.explanation for f in c3_findings if f.severity == FindingSeverity.BLOCK]},
                )
                return case

            case.approved_snapshot_id = case.latest_snapshot_id
            await self._transition_case(case, CaseState.AWAITING_APPROVAL, actor="orchestrator")
            return case

    async def hold_case(
        self, case_id: str, *, duration_seconds: int = 900, actor: str = "user"
    ) -> Case:
        if duration_seconds <= 0:
            raise ValidationError("Hold duration must be positive")
        async with self.store.atomic():
            case = await self.store.get_case(case_id, for_update=True)
            if case is None:
                raise NotFoundError(f"Case {case_id} not found")
            case.hold_expires_at = utcnow() + timedelta(seconds=duration_seconds)
            await self._transition_case(
                case,
                CaseState.HELD,
                actor=actor,
                payload={"hold_expires_at": case.hold_expires_at.isoformat()},
            )
            await self.store.enqueue_recheck_job(
                RecheckJob(
                    case_id=case.case_id,
                    checkpoint=Checkpoint.C7_BACKGROUND_SWEEP.value,
                    run_after=utcnow(),
                )
            )
            return case

    async def resume_case(self, case_id: str, *, actor: str = "user") -> Case:
        async with self.store.atomic():
            case = await self.store.get_case(case_id, for_update=True)
            if case is None:
                raise NotFoundError(f"Case {case_id} not found")
            mandate = await self.store.get_mandate(case.mandate_id)
            if mandate is None:
                raise NotFoundError(f"Mandate {case.mandate_id} not found")
            if case.hold_expires_at and utcnow() > case.hold_expires_at:
                await self._transition_case(case, CaseState.EXPIRED, actor="recheck")
                return case

            catalog_item = await self.catalog.get(case.proposal.product_id)
            _, findings, blocked, drifted = await self._run_recheck_pipeline(
                case=case,
                mandate=mandate,
                checkpoint=Checkpoint.C7_BACKGROUND_SWEEP,
                catalog_item=catalog_item,
                payment_evidence=None,
                actor="recheck",
            )
            if drifted:
                await self._transition_case(
                    case,
                    CaseState.NEEDS_RECONFIRM,
                    actor="drift_detector",
                    payload={"reasons": [f.explanation for f in findings if f.severity == FindingSeverity.BLOCK]},
                )
                await self._notify(
                    "NEEDS_RECONFIRM",
                    case.case_id,
                    "Cart details drifted during hold; reconfirmation required.",
                    {"findings": [f.model_dump(mode="json") for f in findings]},
                )
                return case
            if blocked:
                await self._transition_case(case, CaseState.BLOCKED, actor="policy_engine")
                return case

            await self._transition_case(case, CaseState.AWAITING_APPROVAL, actor=actor)
            return case

    async def recheck_case(
        self,
        case_id: str,
        *,
        checkpoint: Checkpoint = Checkpoint.C7_BACKGROUND_SWEEP,
        actor: str = "recheck",
    ) -> Case:
        async with self.store.atomic():
            case = await self.store.get_case(case_id, for_update=True)
            if case is None:
                raise NotFoundError(f"Case {case_id} not found")
            if case.state not in OPEN_CASE_STATES:
                return case
            mandate = await self.store.get_mandate(case.mandate_id)
            if mandate is None:
                raise NotFoundError(f"Mandate {case.mandate_id} not found")

            catalog_item = await self.catalog.get(case.proposal.product_id)
            payment_evidence = (
                await self.payment.get_order(case.paypal_order_id) if case.paypal_order_id else None
            )
            _, findings, blocked, drifted = await self._run_recheck_pipeline(
                case=case,
                mandate=mandate,
                checkpoint=checkpoint,
                catalog_item=catalog_item,
                payment_evidence=payment_evidence,
                actor=actor,
            )
            if drifted and case.state in {CaseState.HELD, CaseState.AWAITING_APPROVAL, CaseState.APPROVED, CaseState.AUTHORIZED}:
                await self._transition_case(
                    case,
                    CaseState.NEEDS_RECONFIRM,
                    actor="drift_detector",
                    event_type="DRIFT_DETECTED",
                    payload={"reasons": [f.explanation for f in findings if f.severity == FindingSeverity.BLOCK]},
                )
                await self._notify(
                    "NEEDS_RECONFIRM",
                    case.case_id,
                    "Drift detected on recheck; reconfirmation required.",
                )
            elif blocked and case.state in OPEN_CASE_STATES:
                await self._transition_case(
                    case,
                    CaseState.BLOCKED,
                    actor="policy_engine",
                    payload={"reasons": [f.explanation for f in findings if f.severity == FindingSeverity.BLOCK]},
                )
            return case

    async def approve(self, case_id: str, *, actor: str = "user") -> Case:
        """
        Checkpoint C4: Approve click -> fresh recheck -> Approved (or NEEDS_RECONFIRM / BLOCKED).
        """
        async with self.store.atomic():
            case = await self.store.get_case(case_id, for_update=True)
            if case is None:
                raise NotFoundError(f"Case {case_id} not found")
            mandate = await self.store.get_mandate(case.mandate_id)
            if mandate is None:
                raise NotFoundError(f"Mandate {case.mandate_id} not found")

            # If reconfirming after drift, acknowledge current catalog as new baseline only after passing rules
            reconfirming = case.state == CaseState.NEEDS_RECONFIRM
            catalog_item = await self.catalog.get(case.proposal.product_id)

            if reconfirming:
                case.approved_snapshot_id = None
                if catalog_item is not None and catalog_item.in_stock:
                    case.proposal.claimed_unit_price = catalog_item.price
                    case.proposal.claimed_total = catalog_item.price * case.proposal.quantity
                    case.proposal.claimed_seller_id = catalog_item.seller_id
                    case.proposal.claimed_payee_id = catalog_item.payee_id
                    await self.store.append_ledger(
                        case_id=case.case_id,
                        mandate_id=mandate.mandate_id,
                        actor=actor,
                        event_type="RECONFIRM_ACCEPTED_NEW_TERMS",
                        payload={
                            "unit_price": catalog_item.price.to_str(),
                            "seller_id": catalog_item.seller_id,
                            "payee_id": catalog_item.payee_id,
                        },
                    )

            snap, findings, blocked, drifted = await self._run_recheck_pipeline(
                case=case,
                mandate=mandate,
                checkpoint=Checkpoint.C4_APPROVE_CLICK,
                catalog_item=catalog_item,
                payment_evidence=None,
                actor=actor,
            )
            if drifted:
                await self._transition_case(
                    case,
                    CaseState.NEEDS_RECONFIRM,
                    actor="drift_detector",
                    event_type="DRIFT_DETECTED",
                    payload={"reasons": [f.explanation for f in findings if f.severity == FindingSeverity.BLOCK]},
                )
                return case
            if blocked:
                # Note: if catalog price drifted relative to proposal claim, PolicyEngine/Merger flags BLOCK
                if not reconfirming or any(
                    f.source.startswith("rule:") and f.severity == FindingSeverity.BLOCK
                    for f in findings
                ):
                    await self._transition_case(
                        case,
                        CaseState.BLOCKED,
                        actor="policy_engine",
                        payload={"reasons": [f.explanation for f in findings if f.severity == FindingSeverity.BLOCK]},
                    )
                    raise PolicyBlockedError(
                        "; ".join(f.explanation for f in findings if f.severity == FindingSeverity.BLOCK)
                    )

            case.approved_snapshot_id = snap.snapshot_id
            await self._transition_case(case, CaseState.APPROVED, actor=actor)
            return case

    async def authorize(
        self,
        case_id: str,
        *,
        existing_order_id: str | None = None,
        actor: str = "orchestrator",
    ) -> Case:
        """Create/fetch PayPal AUTHORIZE order and authorize funds (hold without capture)."""
        async with self.store.atomic():
            case = await self.store.get_case(case_id, for_update=True)
            if case is None:
                raise NotFoundError(f"Case {case_id} not found")
            if case.state != CaseState.APPROVED:
                await self._transition_case(case, CaseState.AUTHORIZED, actor=actor)  # logs illegal attempt

            snap = (
                await self.store.get_snapshot(case.approved_snapshot_id)
                if case.approved_snapshot_id
                else None
            )
            if snap is None:
                raise ValidationError("Case lacks approved snapshot before authorization")

            order_id = existing_order_id or case.paypal_order_id
            if order_id is None:
                order_ev = await self.payment.create_order(
                    case_id=case.case_id,
                    amount=snap.total_amount,
                    payee_id=snap.payee_id,
                    description=snap.title,
                    request_id=f"{case.case_id}-create",
                )
                order_id = order_ev.order_id

            auth_ev = await self.payment.authorize_order(
                order_id, request_id=f"{case.case_id}-auth"
            )
            case.paypal_order_id = auth_ev.order_id
            case.paypal_authorization_id = auth_ev.authorization_id
            await self._transition_case(
                case,
                CaseState.AUTHORIZED,
                actor=actor,
                payload={
                    "order_id": auth_ev.order_id,
                    "authorization_id": auth_ev.authorization_id,
                    "amount": auth_ev.amount.to_str(),
                },
            )
            return case

    async def capture(self, case_id: str, *, actor: str = "orchestrator") -> Case:
        """
        Checkpoint C5 (pre-capture final gate -> capture or void) followed by
        Checkpoint C6 (ProofGuard post-capture verification -> VERIFIED or FLAGGED).
        """
        async with self.store.atomic():
            case = await self.store.get_case(case_id, for_update=True)
            if case is None:
                raise NotFoundError(f"Case {case_id} not found")
            mandate = await self.store.get_mandate(case.mandate_id)
            if mandate is None:
                raise NotFoundError(f"Mandate {case.mandate_id} not found")

            if case.state not in {CaseState.APPROVED, CaseState.AUTHORIZED}:
                await self._transition_case(case, CaseState.CAPTURED, actor=actor)

            if case.paypal_order_id is None or case.paypal_authorization_id is None:
                raise ValidationError("Case must be authorized on PayPal before capture")

            # C5: Fresh fetch from catalog AND authoritative PayPal order!
            catalog_item = await self.catalog.get(case.proposal.product_id)
            paypal_order = await self.payment.get_order(case.paypal_order_id)
            _, c5_findings, c5_blocked, c5_drifted = await self._run_recheck_pipeline(
                case=case,
                mandate=mandate,
                checkpoint=Checkpoint.C5_PRE_CAPTURE_GATE,
                catalog_item=catalog_item,
                payment_evidence=paypal_order,
                actor="policy_engine",
            )

            if c5_blocked or c5_drifted:
                # Fail closed: IMMEDIATELY VOID the PayPal authorization!
                try:
                    await self.payment.void_authorization(
                        case.paypal_authorization_id,
                        request_id=f"{case.case_id}-void-c5",
                    )
                    await self.store.append_ledger(
                        case_id=case.case_id,
                        mandate_id=mandate.mandate_id,
                        actor="orchestrator",
                        event_type="PAYPAL_HOLD_VOIDED",
                        payload={"authorization_id": case.paypal_authorization_id},
                    )
                except Exception as void_exc:
                    await self.store.append_ledger(
                        case_id=case.case_id,
                        mandate_id=mandate.mandate_id,
                        actor="orchestrator",
                        event_type="PAYPAL_VOID_FAILED",
                        payload={"error": str(void_exc)},
                    )

                target_state = CaseState.NEEDS_RECONFIRM if (c5_drifted and not any(
                    f.code in {"PAYEE_MISMATCH", "AMOUNT_MISMATCH"} for f in c5_findings
                )) else CaseState.BLOCKED
                await self._transition_case(
                    case,
                    target_state,
                    actor="policy_engine",
                    payload={"reasons": [f.explanation for f in c5_findings if f.severity == FindingSeverity.BLOCK]},
                )
                raise PolicyBlockedError(
                    "; ".join(f.explanation for f in c5_findings if f.severity == FindingSeverity.BLOCK)
                )

            # C5 passed -> deterministic capture!
            cap_ev = await self.payment.capture_authorization(
                case.paypal_authorization_id,
                request_id=f"{case.case_id}-capture",
            )
            case.paypal_capture_id = cap_ev.capture_id
            await self._transition_case(
                case,
                CaseState.CAPTURED,
                actor=actor,
                payload={"capture_id": cap_ev.capture_id, "amount": cap_ev.amount.to_str()},
            )

            # Update mandate cumulative spend counters atomically
            cur_total = mandate.spent_total or Money.zero(mandate.max_total.currency)
            cur_day = mandate.spent_today or Money.zero(mandate.max_total.currency)
            cur_week = mandate.spent_this_week or Money.zero(mandate.max_total.currency)
            mandate.spent_total = cur_total + cap_ev.amount
            mandate.spent_today = cur_day + cap_ev.amount
            mandate.spent_this_week = cur_week + cap_ev.amount
            mandate.tx_count += 1
            mandate.updated_at = utcnow()
            await self.store.save_mandate(mandate)

            # C6: ProofGuard post-capture comparison
            approved_snap = (
                await self.store.get_snapshot(case.approved_snapshot_id)
                if case.approved_snapshot_id
                else None
            )
            captured_snap, _ = build_snapshot(
                case_id=case.case_id,
                checkpoint=Checkpoint.C6_POST_CAPTURE_PROOFGUARD.value,
                mandate=mandate,
                proposal=case.proposal,
                catalog_item=catalog_item,
                payment_evidence=cap_ev,
            )
            await self.store.save_snapshot(captured_snap)
            case.latest_snapshot_id = captured_snap.snapshot_id

            pg_result: ProofGuardResult = verify_post_capture_proof(
                mandate=mandate,
                approved_snapshot=approved_snap,
                captured_snapshot=captured_snap,
                paypal_evidence=cap_ev,
            )
            case.last_findings = pg_result.findings
            await self.store.save_case(case)

            if pg_result.verified:
                await self._transition_case(
                    case,
                    CaseState.VERIFIED,
                    actor="proofguard",
                    event_type="PROOFGUARD_VERIFIED",
                    payload={"summary": pg_result.summary, "capture_id": cap_ev.capture_id},
                )
            else:
                await self._transition_case(
                    case,
                    CaseState.FLAGGED,
                    actor="proofguard",
                    event_type="PROOFGUARD_FLAGGED",
                    payload={"summary": pg_result.summary, "capture_id": cap_ev.capture_id},
                )
                await self._notify("FLAGGED", case.case_id, pg_result.summary)

            return case

    async def approve_and_capture(self, case_id: str, *, actor: str = "user") -> Case:
        """Convenience unified path: approve (C4) -> authorize -> C5 -> capture -> ProofGuard (C6)."""
        approved = await self.approve(case_id, actor=actor)
        if approved.state != CaseState.APPROVED:
            return approved
        await self.authorize(case_id, actor=actor)
        return await self.capture(case_id, actor=actor)

    async def cancel(self, case_id: str, *, reason: str = "User cancelled", actor: str = "user") -> Case:
        async with self.store.atomic():
            case = await self.store.get_case(case_id, for_update=True)
            if case is None:
                raise NotFoundError(f"Case {case_id} not found")
            if case.paypal_authorization_id and case.state == CaseState.AUTHORIZED:
                try:
                    await self.payment.void_authorization(
                        case.paypal_authorization_id, request_id=f"{case.case_id}-cancel-void"
                    )
                    await self.store.append_ledger(
                        case_id=case.case_id,
                        mandate_id=case.mandate_id,
                        actor=actor,
                        event_type="PAYPAL_HOLD_VOIDED",
                        payload={"authorization_id": case.paypal_authorization_id},
                    )
                except PaymentProviderError as exc:
                    await self.store.append_ledger(
                        case_id=case.case_id,
                        mandate_id=case.mandate_id,
                        actor=actor,
                        event_type="PAYPAL_VOID_FAILED",
                        payload={"error": str(exc)},
                    )
            await self._transition_case(
                case, CaseState.CANCELLED, actor=actor, payload={"reason": reason}
            )
            return case

    async def revoke_all(self, *, reason: str = "Kill switch /revoke", actor: str = "user") -> dict[str, Any]:
        """Kill switch: revoke active mandates, freeze/cancel open cases, void all PayPal authorizations."""
        revoked_mandates: list[str] = []
        cancelled_cases: list[str] = []
        voided_authorizations: list[str] = []

        async with self.store.atomic():
            mandates = await self.store.list_mandates(limit=200)
            for m in mandates:
                if m.status in {MandateStatus.DRAFT, MandateStatus.ACTIVE}:
                    m.status = MandateStatus.REVOKED
                    m.updated_at = utcnow()
                    await self.store.save_mandate(m)
                    revoked_mandates.append(m.mandate_id)
                    await self.store.append_ledger(
                        case_id=None,
                        mandate_id=m.mandate_id,
                        actor=actor,
                        event_type="MANDATE_REVOKED",
                        payload={"reason": reason},
                    )

            open_cases = await self.store.list_open_cases()
            for c in open_cases:
                if c.paypal_authorization_id:
                    try:
                        await self.payment.void_authorization(
                            c.paypal_authorization_id, request_id=f"{c.case_id}-revoke-void"
                        )
                        voided_authorizations.append(c.paypal_authorization_id)
                    except Exception:
                        pass
                await self._transition_case(
                    c,
                    CaseState.CANCELLED,
                    actor=actor,
                    event_type="KILL_SWITCH_CANCELLED",
                    payload={"reason": reason},
                )
                cancelled_cases.append(c.case_id)

        return {
            "revoked_mandates": revoked_mandates,
            "cancelled_cases": cancelled_cases,
            "voided_authorizations": voided_authorizations,
        }

    # ------------------------------------------------------------------
    # Background Recheck Sweep (C7) & Webhooks (C8)
    # ------------------------------------------------------------------

    async def sweep_open_cases(self, *, actor: str = "recheck_worker") -> list[str]:
        """C7 background sweep over HELD and AUTHORIZED cases."""
        cases = await self.store.list_held_or_authorized_cases()
        processed: list[str] = []
        for c in cases:
            await self.recheck_case(
                c.case_id, checkpoint=Checkpoint.C7_BACKGROUND_SWEEP, actor=actor
            )
            processed.append(c.case_id)
        return processed

    async def process_due_recheck_jobs(self, *, limit: int = 10) -> int:
        jobs = await self.store.claim_due_recheck_jobs(now=utcnow(), limit=limit)
        for job in jobs:
            try:
                cp = Checkpoint(job.checkpoint)
                await self.recheck_case(job.case_id, checkpoint=cp, actor="recheck_worker")
                await self.store.finish_recheck_job(job.job_id, status="DONE")
            except Exception as exc:
                await self.store.finish_recheck_job(
                    job.job_id, status="FAILED", error=str(exc)
                )
        return len(jobs)

    async def handle_webhook(
        self,
        *,
        event_id: str,
        event_type: str,
        case_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Deduplicate webhook by event_id and enqueue C8 reconcile job atomically."""
        async with self.store.atomic():
            is_new = await self.store.record_webhook_if_new(event_id, event_type, payload)
            if not is_new:
                await self.store.append_ledger(
                    case_id=case_id,
                    mandate_id=None,
                    actor="paypal_webhook",
                    event_type="WEBHOOK_DUPLICATE_IGNORED",
                    payload={"event_id": event_id, "event_type": event_type},
                )
                return {"accepted": True, "duplicate": True, "event_id": event_id}

            await self.store.append_ledger(
                case_id=case_id,
                mandate_id=None,
                actor="paypal_webhook",
                event_type="WEBHOOK_RECEIVED",
                payload={"event_id": event_id, "event_type": event_type},
            )
            if case_id:
                await self.store.enqueue_recheck_job(
                    RecheckJob(
                        case_id=case_id,
                        checkpoint=Checkpoint.C8_WEBHOOK_RECONCILE.value,
                        run_after=utcnow(),
                    )
                )
            return {"accepted": True, "duplicate": False, "event_id": event_id}

    # ------------------------------------------------------------------
    # Plain-English /why & Snapshot Diff
    # ------------------------------------------------------------------

    async def explain_case(self, case_id: str) -> dict[str, Any]:
        case = await self.store.get_case(case_id)
        if case is None:
            raise NotFoundError(f"Case {case_id} not found")
        blocks = [f for f in case.last_findings if f.severity == FindingSeverity.BLOCK]
        warns = [f for f in case.last_findings if f.severity == FindingSeverity.WARN]
        infos = [f for f in case.last_findings if f.severity == FindingSeverity.INFO]

        diff_findings: list[Finding] = []
        if case.approved_snapshot_id and case.latest_snapshot_id and case.approved_snapshot_id != case.latest_snapshot_id:
            snap_a = await self.store.get_snapshot(case.approved_snapshot_id)
            snap_b = await self.store.get_snapshot(case.latest_snapshot_id)
            if snap_a and snap_b:
                diff_findings = diff(snap_a, snap_b)

        return {
            "case_id": case.case_id,
            "state": case.state.value,
            "plain_english_reasons": [f.explanation for f in blocks + warns]
            or ["All deterministic checks passed cleanly."],
            "blocking_findings": [f.model_dump(mode="json") for f in blocks],
            "warning_findings": [f.model_dump(mode="json") for f in warns],
            "passed_checks": [f.model_dump(mode="json") for f in infos],
            "snapshot_diff": [f.model_dump(mode="json") for f in diff_findings],
        }

    async def get_case_receipt(
        self,
        case_id: str,
        *,
        narrative_mode: Literal["auto", "deterministic", "llm"] = "auto",
    ) -> IntentReceipt:
        case = await self.store.get_case(case_id)
        if case is None:
            raise NotFoundError(f"Case {case_id} not found")
        snapshots = await self.store.list_snapshots(case_id)
        latest_snapshot = snapshots[-1] if snapshots else None
        entries, _ = await self.store.list_ledger(case_id=case_id, limit=1, sort_dir="desc")
        latest_entry = entries[0] if entries else None
        llm_to_use = None if narrative_mode == "deterministic" else self.llm
        return await generate_intent_receipt(
            case=case,
            snapshot=latest_snapshot,
            latest_ledger_entry=latest_entry,
            llm=llm_to_use,
        )

    async def verify_ledger(self) -> dict[str, Any]:
        entries = await self.store.iter_all_ledger()
        return verify_ledger_chain(entries).model_dump(mode="json")
