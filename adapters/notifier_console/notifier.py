from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("mandate.notifier")


@dataclass
class RecordedNotification:
    event: str
    case_id: str | None
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class ConsoleNotifier:
    """Console + in-memory recording Notifier (also reusable for Email-agent demo)."""

    def __init__(self) -> None:
        self.events: list[RecordedNotification] = []

    async def notify(
        self,
        *,
        event: str,
        case_id: str | None,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        rec = RecordedNotification(
            event=event,
            case_id=case_id,
            message=message,
            details=details or {},
        )
        self.events.append(rec)
        logger.info("NOTIFY [%s] case=%s: %s", event, case_id, message)


class WebhookNotifier:
    """Zapier MCP / Slack webhook Notifier adapter."""

    def __init__(self, webhook_url: str, *, timeout: float = 5.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    async def notify(
        self,
        *,
        event: str,
        case_id: str | None,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(
                self.webhook_url,
                json={
                    "event": event,
                    "case_id": case_id,
                    "message": message,
                    "details": details or {},
                },
            )
