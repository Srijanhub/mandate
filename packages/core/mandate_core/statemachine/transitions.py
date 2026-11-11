from __future__ import annotations

from mandate_core.domain.models import CaseState, MandateStatus

MANDATE_TRANSITIONS: dict[MandateStatus, set[MandateStatus]] = {
    MandateStatus.DRAFT: {MandateStatus.ACTIVE, MandateStatus.REVOKED, MandateStatus.EXPIRED},
    MandateStatus.ACTIVE: {MandateStatus.REVOKED, MandateStatus.EXPIRED},
    MandateStatus.REVOKED: set(),
    MandateStatus.EXPIRED: set(),
}

TERMINAL_CASE_STATES: frozenset[CaseState] = frozenset(
    {
        CaseState.VERIFIED,
        CaseState.FLAGGED,
        CaseState.CANCELLED,
        CaseState.BLOCKED,
        CaseState.EXPIRED,
    }
)

OPEN_CASE_STATES: frozenset[CaseState] = frozenset(set(CaseState) - TERMINAL_CASE_STATES)

CASE_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.PROPOSED: {
        CaseState.CART_LOCKED,
        CaseState.BLOCKED,
        CaseState.CANCELLED,
        CaseState.EXPIRED,
    },
    CaseState.CART_LOCKED: {
        CaseState.CHECKED,
        CaseState.BLOCKED,
        CaseState.NEEDS_RECONFIRM,
        CaseState.CANCELLED,
        CaseState.EXPIRED,
    },
    CaseState.CHECKED: {
        CaseState.AWAITING_APPROVAL,
        CaseState.BLOCKED,
        CaseState.NEEDS_RECONFIRM,
        CaseState.CANCELLED,
        CaseState.EXPIRED,
    },
    CaseState.AWAITING_APPROVAL: {
        CaseState.APPROVED,
        CaseState.HELD,
        CaseState.CANCELLED,
        CaseState.BLOCKED,
        CaseState.NEEDS_RECONFIRM,
        CaseState.EXPIRED,
    },
    CaseState.HELD: {
        CaseState.AWAITING_APPROVAL,
        CaseState.NEEDS_RECONFIRM,
        CaseState.CANCELLED,
        CaseState.BLOCKED,
        CaseState.EXPIRED,
    },
    CaseState.NEEDS_RECONFIRM: {
        CaseState.AWAITING_APPROVAL,
        CaseState.APPROVED,
        CaseState.CANCELLED,
        CaseState.BLOCKED,
        CaseState.EXPIRED,
    },
    CaseState.APPROVED: {
        CaseState.AUTHORIZED,
        CaseState.CAPTURED,
        CaseState.CANCELLED,
        CaseState.BLOCKED,
        CaseState.NEEDS_RECONFIRM,
        CaseState.EXPIRED,
    },
    CaseState.AUTHORIZED: {
        CaseState.CAPTURED,
        CaseState.HELD,
        CaseState.CANCELLED,
        CaseState.BLOCKED,
        CaseState.NEEDS_RECONFIRM,
        CaseState.EXPIRED,
    },
    CaseState.CAPTURED: {
        CaseState.VERIFIED,
        CaseState.FLAGGED,
    },
    CaseState.VERIFIED: set(),
    CaseState.FLAGGED: set(),
    CaseState.CANCELLED: set(),
    CaseState.BLOCKED: set(),
    CaseState.EXPIRED: set(),
}


def can_transition_case(current: CaseState, target: CaseState) -> bool:
    return target in CASE_TRANSITIONS.get(current, set())


def can_transition_mandate(current: MandateStatus, target: MandateStatus) -> bool:
    return target in MANDATE_TRANSITIONS.get(current, set())
