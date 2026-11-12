from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mandate_core.domain.errors import CommandParseError

ControlPlaneSource = Literal["user_command", "ui_button"]


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: list[str]
    raw_text: str


SUPPORTED_COMMANDS = frozenset(
    {
        "mandate",
        "confirm",
        "amend",
        "options",
        "pick",
        "approve",
        "cancel",
        "hold",
        "resume",
        "recheck",
        "status",
        "why",
        "receipt",
        "ledger",
        "revoke",
        "help",
    }
)


def parse_command(
    text: str,
    *,
    source: str = "user_command",
) -> ParsedCommand | None:
    """
    Deterministic pre-LLM slash command parser.
    Control-plane vs. data-plane boundary:
      - Only authenticated user messages ('user_command') or UI buttons ('ui_button') may execute commands.
      - Any untrusted data source (product text, agent output, catalog descriptions) is ALWAYS rejected.
    Returns None if text is natural language (intent-only, never executes an action).
    """
    if source not in {"user_command", "ui_button"}:
        raise CommandParseError(
            f"Untrusted source '{source}' cannot invoke control-plane commands",
            code="UNTRUSTED_CONTROL_PLANE_SOURCE",
        )

    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    body = stripped[1:].strip()
    if not body:
        raise CommandParseError("Empty command after '/'")

    parts = body.split()
    name = parts[0].lower()
    args = parts[1:]

    if name not in SUPPORTED_COMMANDS:
        raise CommandParseError(f"Unknown command '/{name}'. Type /help for supported commands.")

    return ParsedCommand(name=name, args=args, raw_text=stripped)
