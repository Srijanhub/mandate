from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from apps.api.dependencies import AppContainer, get_container

router = APIRouter(prefix="/commands", tags=["Commands"])


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    source: Literal["user_command", "ui_button", "product_text", "agent_output"] = "user_command"
    actor: str = "user"
    case_id: str | None = None
    mandate_id: str | None = None


@router.post("")
async def execute_command(
    body: CommandRequest,
    container: AppContainer = Depends(get_container),
) -> dict[str, Any]:
    """
    Unified control-plane command endpoint.
    Deterministic `/` parser runs BEFORE any LLM call; untrusted sources are blocked.
    Natural language (non-`/` text) is treated as intent-only and compiles a DRAFT mandate.
    """
    result = await container.commands.execute_raw(
        body.text,
        source=body.source,
        actor=body.actor,
        case_id=body.case_id,
        mandate_id=body.mandate_id,
    )
    if not result["is_command"]:
        # Natural language never executes an action directly; only drafts an unconfirmed Mandate.
        drafted = await container.commands.compile_and_draft(body.text, body.actor)  # type: ignore[misc]
        return {"is_command": False, "action": "mandate_draft_only", **drafted}
    return result
