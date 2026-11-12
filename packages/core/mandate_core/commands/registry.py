from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from mandate_core.commands.parser import ParsedCommand, parse_command
from mandate_core.domain.errors import AuthorizationError, CommandParseError, NotFoundError
from mandate_core.domain.models import CaseState, Money
from mandate_core.statemachine import Orchestrator


class EmptyArgs(BaseModel):
    pass


class MandateCmdArgs(BaseModel):
    text: str = Field(min_length=1)


class AmendCmdArgs(BaseModel):
    field: str
    value: str


class PickCmdArgs(BaseModel):
    index: int = Field(ge=1)


class HoldCmdArgs(BaseModel):
    duration_seconds: int = Field(default=900, ge=10, le=86400)
    case_id: str | None = None


class OptionalIdArgs(BaseModel):
    case_id: str | None = None


class LedgerCmdArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    allowed_states: frozenset[CaseState] | None
    handler: Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]]


def _parse_duration(raw: str | None) -> int:
    if not raw:
        return 900
    m = re.fullmatch(r"(\d+)\s*(s|m|h)?", raw.strip().lower())
    if not m:
        raise CommandParseError(f"Invalid hold duration {raw!r}; expected e.g. '15m', '1h', or '600'")
    qty = int(m.group(1))
    unit = m.group(2) or "s"
    mult = {"s": 1, "m": 60, "h": 3600}[unit]
    return qty * mult


class CommandRegistry:
    """
    Unified Command Registry backing BOTH slash commands (/approve) and UI buttons.
    One code path, no exceptions.
    """

    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        compile_and_draft: Callable[[str, str], Awaitable[dict[str, Any]]] | None = None,
        run_options: Callable[[str | None, str | None], Awaitable[dict[str, Any]]] | None = None,
        pick_option: Callable[[int, str | None, str | None], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.compile_and_draft = compile_and_draft
        self.run_options = run_options
        self.pick_option = pick_option
        self.specs: dict[str, CommandSpec] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.specs["help"] = CommandSpec(
            name="help",
            description="List all supported Mandate commands",
            args_schema=EmptyArgs,
            allowed_states=None,
            handler=self._handle_help,
        )
        self.specs["mandate"] = CommandSpec(
            name="mandate",
            description="/mandate <text> to compile a mandate, or /mandate show",
            args_schema=MandateCmdArgs,
            allowed_states=None,
            handler=self._handle_mandate,
        )
        self.specs["confirm"] = CommandSpec(
            name="confirm",
            description="/confirm to activate the latest drafted mandate",
            args_schema=EmptyArgs,
            allowed_states=None,
            handler=self._handle_confirm,
        )
        self.specs["amend"] = CommandSpec(
            name="amend",
            description="/amend <field> <value> to create a new mandate version requiring /confirm",
            args_schema=AmendCmdArgs,
            allowed_states=None,
            handler=self._handle_amend,
        )
        self.specs["options"] = CommandSpec(
            name="options",
            description="/options to show or re-run candidate product options",
            args_schema=EmptyArgs,
            allowed_states=None,
            handler=self._handle_options,
        )
        self.specs["pick"] = CommandSpec(
            name="pick",
            description="/pick <n> to select option #n and lock cart",
            args_schema=PickCmdArgs,
            allowed_states=None,
            handler=self._handle_pick,
        )
        self.specs["approve"] = CommandSpec(
            name="approve",
            description="/approve [case_id] to approve & execute PayPal capture + ProofGuard",
            args_schema=OptionalIdArgs,
            allowed_states=frozenset({CaseState.AWAITING_APPROVAL, CaseState.NEEDS_RECONFIRM}),
            handler=self._handle_approve,
        )
        self.specs["cancel"] = CommandSpec(
            name="cancel",
            description="/cancel [case_id] to cancel case and void any PayPal hold",
            args_schema=OptionalIdArgs,
            allowed_states=None,
            handler=self._handle_cancel,
        )
        self.specs["hold"] = CommandSpec(
            name="hold",
            description="/hold [dur] to place case on temporary hold with recheck sweep",
            args_schema=HoldCmdArgs,
            allowed_states=frozenset({CaseState.AWAITING_APPROVAL, CaseState.AUTHORIZED}),
            handler=self._handle_hold,
        )
        self.specs["resume"] = CommandSpec(
            name="resume",
            description="/resume [case_id] to recheck and resume a held case",
            args_schema=OptionalIdArgs,
            allowed_states=frozenset({CaseState.HELD}),
            handler=self._handle_resume,
        )
        self.specs["recheck"] = CommandSpec(
            name="recheck",
            description="/recheck [case_id] to force a full deterministic + AI recheck",
            args_schema=OptionalIdArgs,
            allowed_states=None,
            handler=self._handle_recheck,
        )
        self.specs["status"] = CommandSpec(
            name="status",
            description="/status [case_id] to inspect case state and last findings",
            args_schema=OptionalIdArgs,
            allowed_states=None,
            handler=self._handle_status,
        )
        self.specs["why"] = CommandSpec(
            name="why",
            description="/why [case_id] to explain rules and snapshot diffs in plain English",
            args_schema=OptionalIdArgs,
            allowed_states=None,
            handler=self._handle_why,
        )
        self.specs["receipt"] = CommandSpec(
            name="receipt",
            description="/receipt [case_id] to generate a cryptographic SHA-256 Intent Receipt",
            args_schema=OptionalIdArgs,
            allowed_states=None,
            handler=self._handle_receipt,
        )
        self.specs["ledger"] = CommandSpec(
            name="ledger",
            description="/ledger [n] to print the last n hash-chained ledger entries",
            args_schema=LedgerCmdArgs,
            allowed_states=None,
            handler=self._handle_ledger,
        )
        self.specs["revoke"] = CommandSpec(
            name="revoke",
            description="/revoke kill switch: freezes mandates, cancels open cases, voids holds",
            args_schema=EmptyArgs,
            allowed_states=None,
            handler=self._handle_revoke,
        )

    async def execute_raw(
        self,
        raw_text: str,
        *,
        source: str = "user_command",
        actor: str = "user",
        case_id: str | None = None,
        mandate_id: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        parsed: ParsedCommand | None = parse_command(raw_text, source=source)
        if parsed is None:
            return {"is_command": False, "natural_language": raw_text.strip()}

        spec = self.specs[parsed.name]
        validated = self._bind_args(parsed, case_id=case_id)
        ctx = {"actor": actor, "case_id": case_id, "mandate_id": mandate_id, "owner_id": owner_id}
        result = await spec.handler(validated, ctx)
        return {"is_command": True, "command": parsed.name, **result}

    def _bind_args(self, parsed: ParsedCommand, *, case_id: str | None) -> BaseModel:
        n = parsed.name
        a = parsed.args
        if n in {"help", "confirm", "options", "revoke"}:
            return EmptyArgs()
        if n == "mandate":
            if not a:
                raise CommandParseError("Usage: /mandate <text> or /mandate show")
            return MandateCmdArgs(text=" ".join(a))
        if n == "amend":
            if len(a) < 2:
                raise CommandParseError("Usage: /amend <field> <value>")
            return AmendCmdArgs(field=a[0], value=" ".join(a[1:]))
        if n == "pick":
            if not a or not a[0].isdigit():
                raise CommandParseError("Usage: /pick <option_number>")
            return PickCmdArgs(index=int(a[0]))
        if n == "hold":
            dur = _parse_duration(a[0] if a else None)
            target_id = a[1] if len(a) > 1 else case_id
            return HoldCmdArgs(duration_seconds=dur, case_id=target_id)
        if n == "ledger":
            lim = int(a[0]) if (a and a[0].isdigit()) else 20
            return LedgerCmdArgs(limit=lim)
        # approve, cancel, resume, recheck, status, why
        target_id = a[0] if a else case_id
        return OptionalIdArgs(case_id=target_id)

    async def _assert_case_owner(self, case_id: str, owner_id: str | None) -> None:
        if not owner_id:
            return
        case = await self.orchestrator.store.get_case(case_id)
        if case is None:
            raise NotFoundError(f"Case {case_id} not found")
        mandate = await self.orchestrator.store.get_mandate(case.mandate_id)
        if mandate is not None and mandate.owner_id != owner_id:
            raise AuthorizationError("Access denied: case belongs to another user")

    async def _resolve_case_id(
        self, args_case_id: str | None, *, owner_id: str | None = None
    ) -> str:
        if args_case_id:
            await self._assert_case_owner(args_case_id, owner_id)
            return args_case_id
        latest = await self.orchestrator.store.get_latest_case(owner_id=owner_id)
        if latest is None:
            raise NotFoundError("No active case found; pass a case_id explicitly")
        return latest.case_id

    async def _handle_help(self, _args: EmptyArgs, _ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "commands": [
                {"name": f"/{s.name}", "description": s.description}
                for s in self.specs.values()
            ]
        }

    async def _handle_mandate(self, args: MandateCmdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        owner_id = ctx.get("owner_id")
        if args.text.strip().lower() == "show":
            m = (
                await self.orchestrator.store.get_mandate(ctx["mandate_id"])
                if ctx.get("mandate_id")
                else await self.orchestrator.store.get_latest_mandate(owner_id=owner_id)
            )
            if m is None:
                raise NotFoundError("No mandate exists yet")
            if owner_id and m.owner_id != owner_id:
                raise AuthorizationError("Access denied: mandate belongs to another user")
            return {"mandate": m.model_dump(mode="json")}
        if self.compile_and_draft is None:
            raise CommandParseError("Mandate compiler callback is not wired")
        return await self.compile_and_draft(args.text, ctx["actor"])

    async def _handle_confirm(self, _args: EmptyArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        m = await self.orchestrator.confirm_mandate(
            ctx.get("mandate_id"), actor=ctx["actor"], owner_id=ctx.get("owner_id")
        )
        return {"mandate": m.model_dump(mode="json")}

    async def _handle_amend(self, args: AmendCmdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        owner_id = ctx.get("owner_id")
        field = args.field.strip().lower()
        updates: dict[str, Any] = {}
        if field == "max_total":
            latest = await self.orchestrator.store.get_latest_mandate(owner_id=owner_id)
            currency = latest.max_total.currency if latest else "USD"
            updates["max_total"] = Money.of(args.value, currency)
        elif field == "require_verified_seller":
            updates["require_verified_seller"] = args.value.strip().lower() in {"true", "1", "yes"}
        elif field == "max_transactions":
            updates["max_transactions"] = int(args.value)
        else:
            raise CommandParseError(f"Field '{field}' cannot be amended via /amend")
        m = await self.orchestrator.amend_mandate(
            ctx.get("mandate_id"), updates=updates, actor=ctx["actor"], owner_id=owner_id
        )
        return {"mandate": m.model_dump(mode="json"), "needs_confirm": True}

    async def _handle_options(self, _args: EmptyArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        if self.run_options is None:
            return {"options": [], "message": "Catalog search service not attached"}
        return await self.run_options(ctx.get("mandate_id"), ctx.get("owner_id"))

    async def _handle_pick(self, args: PickCmdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        if self.pick_option is None:
            raise CommandParseError("Option picker callback is not wired")
        return await self.pick_option(args.index, ctx.get("mandate_id"), ctx.get("owner_id"))

    async def _handle_approve(self, args: OptionalIdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        cid = await self._resolve_case_id(args.case_id, owner_id=ctx.get("owner_id"))
        case = await self.orchestrator.approve_and_capture(cid, actor=ctx["actor"])
        return {"case": case.model_dump(mode="json")}

    async def _handle_cancel(self, args: OptionalIdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        cid = await self._resolve_case_id(args.case_id, owner_id=ctx.get("owner_id"))
        case = await self.orchestrator.cancel(cid, actor=ctx["actor"])
        return {"case": case.model_dump(mode="json")}

    async def _handle_hold(self, args: HoldCmdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        cid = await self._resolve_case_id(
            args.case_id or ctx.get("case_id"), owner_id=ctx.get("owner_id")
        )
        case = await self.orchestrator.hold_case(
            cid, duration_seconds=args.duration_seconds, actor=ctx["actor"]
        )
        return {"case": case.model_dump(mode="json")}

    async def _handle_resume(self, args: OptionalIdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        cid = await self._resolve_case_id(args.case_id, owner_id=ctx.get("owner_id"))
        case = await self.orchestrator.resume_case(cid, actor=ctx["actor"])
        return {"case": case.model_dump(mode="json")}

    async def _handle_recheck(self, args: OptionalIdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        cid = await self._resolve_case_id(args.case_id, owner_id=ctx.get("owner_id"))
        case = await self.orchestrator.recheck_case(cid, actor=ctx["actor"])
        return {"case": case.model_dump(mode="json")}

    async def _handle_status(self, args: OptionalIdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        cid = await self._resolve_case_id(args.case_id, owner_id=ctx.get("owner_id"))
        case = await self.orchestrator.store.get_case(cid)
        if case is None:
            raise NotFoundError(f"Case {cid} not found")
        return {"case": case.model_dump(mode="json")}

    async def _handle_why(self, args: OptionalIdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        cid = await self._resolve_case_id(args.case_id, owner_id=ctx.get("owner_id"))
        return await self.orchestrator.explain_case(cid)

    async def _handle_receipt(self, args: OptionalIdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        cid = await self._resolve_case_id(args.case_id, owner_id=ctx.get("owner_id"))
        receipt = await self.orchestrator.get_case_receipt(cid)
        return {"receipt": receipt.model_dump(mode="json")}

    async def _handle_ledger(self, args: LedgerCmdArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        entries, total = await self.orchestrator.store.list_ledger(
            owner_id=ctx.get("owner_id"), limit=args.limit, sort_dir="desc"
        )
        return {
            "total_count": total,
            "entries": [e.model_dump(mode="json") for e in entries],
        }

    async def _handle_revoke(self, _args: EmptyArgs, ctx: dict[str, Any]) -> dict[str, Any]:
        return await self.orchestrator.revoke_all(actor=ctx["actor"], owner_id=ctx.get("owner_id"))
