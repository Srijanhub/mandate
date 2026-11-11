from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mandate_core.domain.models import (
    CaseSnapshot,
    Decision,
    EmailProposal,
    Finding,
    FindingSeverity,
    Mandate,
    utcnow,
)


@dataclass(frozen=True)
class RuleContext:
    mandate: Mandate
    snapshot: CaseSnapshot | None = None
    email_proposal: EmailProposal | None = None
    now: datetime | None = None

    @property
    def current_time(self) -> datetime:
        return self.now or utcnow()


RuleFn = Callable[[RuleContext], Finding]

_RULE_REGISTRY: dict[str, dict[str, RuleFn]] = {}


def register_rule(name: str, *, domain: str = "shopping") -> Callable[[RuleFn], RuleFn]:
    """Decorator registering a deterministic policy rule under a domain pack."""

    def decorator(fn: RuleFn) -> RuleFn:
        bucket = _RULE_REGISTRY.setdefault(domain, {})
        bucket[name] = fn
        return fn

    return decorator


def get_registered_rules(domain: str = "shopping") -> dict[str, RuleFn]:
    return dict(_RULE_REGISTRY.get(domain, {}))


def evaluate_rules(
    ctx: RuleContext,
    *,
    enabled_rules: list[str] | None = None,
) -> Decision:
    """
    Evaluate ALL rules in the mandate's domain without short-circuiting so /why
    can present a full rule-by-rule breakdown.
    """
    # Ensure built-in rules are imported and registered
    from mandate_core.rules import builtins as _builtins  # noqa: F401

    domain_rules = get_registered_rules(ctx.mandate.domain)
    if enabled_rules is not None:
        selected: list[tuple[str, RuleFn]] = [
            (name, domain_rules[name]) for name in enabled_rules if name in domain_rules
        ]
    else:
        selected = list(domain_rules.items())

    findings: list[Finding] = []
    for _rule_name, rule_fn in selected:
        findings.append(rule_fn(ctx))

    blocked = [f for f in findings if f.severity == FindingSeverity.BLOCK]
    warned = [f for f in findings if f.severity == FindingSeverity.WARN]

    if blocked:
        verdict = "BLOCK"
        allow = False
        summary = "; ".join(f.explanation for f in blocked)
    elif warned:
        verdict = "WARN"
        allow = True
        summary = "; ".join(f.explanation for f in warned)
    else:
        verdict = "ALLOW"
        allow = True
        summary = f"All {len(findings)} deterministic policy rules passed."

    return Decision(
        allow=allow,
        verdict=verdict,
        findings=findings,
        plain_english_summary=summary,
    )


def load_policy_pack(name: str) -> dict[str, Any]:
    import json
    from pathlib import Path

    pack_path = Path(__file__).parent / "packs" / f"{name}.json"
    if not pack_path.exists():
        raise FileNotFoundError(f"Policy pack {name!r} not found at {pack_path}")
    return json.loads(pack_path.read_text(encoding="utf-8"))
