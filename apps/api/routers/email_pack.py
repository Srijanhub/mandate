from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from mandate_core.domain.models import EmailProposal, Mandate, MandateStatus, Money, utcnow
from mandate_core.rules import RuleContext, evaluate_rules
from pydantic import BaseModel, Field

from apps.api.dependencies import AppContainer, get_container

router = APIRouter(prefix="/packs/email", tags=["Domain-Agnostic Policy Packs"])


class EmailPolicyCheckRequest(BaseModel):
    subject: str
    recipients: list[str] = Field(min_length=1)
    body_preview: str = ""
    max_recipients: int = Field(default=3, ge=1)
    allowed_recipient_domains: list[str] = Field(default_factory=lambda: ["company.com"])


@router.post("/check")
async def check_email_agent_proposal(
    body: EmailPolicyCheckRequest,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """
    Section 9 Demo Beat: Reuses the exact same Mandate Core Rule Engine + Ledger
    for an autonomous email-sending agent (max_recipients + allowlist_domain).
    """
    mandate = Mandate(
        owner_id="demo-user",
        domain="email",
        intent_text=f"Allow email sends to {body.allowed_recipient_domains} (max {body.max_recipients} recipients)",
        max_total=Money.zero("USD"),
        max_recipients=body.max_recipients,
        allowed_recipient_domains=body.allowed_recipient_domains,
        expires_at=utcnow() + timedelta(hours=1),
        status=MandateStatus.ACTIVE,
    )
    prop = EmailProposal(
        mandate_id=mandate.mandate_id,
        subject=body.subject,
        recipients=body.recipients,
        body_preview=body.body_preview,
    )

    decision = evaluate_rules(RuleContext(mandate=mandate, email_proposal=prop))
    entry = await container.store.append_ledger(
        case_id=None,
        mandate_id=mandate.mandate_id,
        actor="email-agent",
        event_type="EMAIL_POLICY_ALLOW" if decision.allow else "EMAIL_POLICY_BLOCK",
        payload={
            "recipients": body.recipients,
            "allow": decision.allow,
            "summary": decision.plain_english_summary,
        },
    )
    return {
        "domain": "email",
        "decision": decision.model_dump(mode="json"),
        "ledger_seq": entry.seq,
    }
