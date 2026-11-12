from __future__ import annotations

from datetime import timedelta
from typing import Any

from mandate_core.domain.models import (
    Mandate,
    MandateStatus,
    Money,
    utcnow,
)

DEFAULT_SELLER_A_ID: str = "SELLER-A-VERIFIED"
DEFAULT_SELLER_B_ID: str = "SELLER-B-ATTACKER"


async def seed_demo_data(
    store: Any,
    *,
    seller_a_id: str = DEFAULT_SELLER_A_ID,
    seller_b_id: str = DEFAULT_SELLER_B_ID,
) -> dict[str, Any]:
    """
    Idempotently seeds initial demo mandates and audit ledger records.
    Safe to run repeatedly; skips items that already exist.
    """
    seeded_mandates: list[str] = []
    seeded_ledger: bool = False

    # Check if shopping mandate already exists
    shopping_mandate = await store.get_mandate("mnd_demo_shopping_01")
    if shopping_mandate is None:
        shopping = Mandate(
            mandate_id="mnd_demo_shopping_01",
            version=1,
            owner_id="demo-user",
            domain="shopping",
            intent_text="Buy a birthday gift or diffuser under $60, verified sellers only, delivered within 3 days",
            max_total=Money.of("60.00", "USD"),
            max_spend_per_day=Money.of("100.00", "USD"),
            max_transactions=5,
            require_verified_seller=True,
            allowed_sellers=[seller_a_id],
            blocked_sellers=[seller_b_id],
            allowed_categories=["home", "gifts", "decor", "candles"],
            blocked_keywords=["crypto", "giftcard", "wire", "subscription"],
            deliver_by=utcnow() + timedelta(days=3),
            expires_at=utcnow() + timedelta(days=7),
            status=MandateStatus.ACTIVE,
        )
        await store.save_mandate(shopping)
        seeded_mandates.append(shopping.mandate_id)

    # Check if email mandate already exists
    email_mandate = await store.get_mandate("mnd_demo_email_01")
    if email_mandate is None:
        email = Mandate(
            mandate_id="mnd_demo_email_01",
            version=1,
            owner_id="demo-user",
            domain="email",
            intent_text="Customer support email triage agent; only internal domains and up to 5 recipients",
            max_total=Money.of("0.00", "USD"),
            max_transactions=20,
            allowed_recipient_domains=["company.com", "trusted-partner.org"],
            max_recipients=5,
            expires_at=utcnow() + timedelta(days=30),
            status=MandateStatus.ACTIVE,
        )
        await store.save_mandate(email)
        seeded_mandates.append(email.mandate_id)

    # Check if ledger is empty; append genesis entry if needed
    entries, total = await store.list_ledger(limit=1)
    if total == 0:
        await store.append_ledger(
            case_id=None,
            mandate_id="mnd_demo_shopping_01",
            actor="system",
            event_type="SYSTEM_INITIALIZED",
            payload={
                "message": "Mandate spending firewall initialized with cryptographic SHA-256 hash-chained ledger.",
                "features": ["advisory_lock", "skip_locked", "wal_mode", "tamper_detection"],
            },
        )
        seeded_ledger = True

    return {
        "seeded": bool(seeded_mandates or seeded_ledger),
        "seeded_mandates": seeded_mandates,
        "seeded_ledger": seeded_ledger,
    }
