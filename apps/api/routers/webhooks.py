from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.dependencies import AppContainer, get_container

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/paypal")
async def paypal_webhook(
    request: Request,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    headers = {k.lower(): v for k, v in request.headers.items()}
    payload = await request.json()

    verified = await container.payment.verify_webhook_signature(headers, payload)
    if not verified:
        raise HTTPException(status_code=401, detail="Invalid PayPal webhook signature")

    event_id = str(payload.get("id") or headers.get("paypal-transmission-id") or "")
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing webhook event id")

    event_type = str(payload.get("event_type") or "UNKNOWN")
    resource = payload.get("resource") or {}
    case_id = resource.get("custom_id") or resource.get("invoice_id")
    if not case_id:
        supp = resource.get("supplementary_data") or {}
        case_id = supp.get("related_ids", {}).get("case_id")

    return await container.orchestrator.handle_webhook(
        event_id=event_id,
        event_type=event_type,
        case_id=case_id,
        payload=payload,
    )
