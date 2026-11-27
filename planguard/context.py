"""Deterministic context for the explanation: what changes and what depends on it.

Claude only gets facts computed here, so it explains the blast radius from real
dependencies (configuration references and current state) instead of guessing.
"""

from __future__ import annotations

from typing import Any

from .plan import Change, Plan, config_address, env_of
from .rules import Finding, Level

_MAX_VALUE_CHARS = 1200
_MAX_DEPENDENTS = 15
_HIDDEN_ATTRS = {"tags_all", "arn", "id", "owner_id", "region"}
_TAG_KEYS = ("Name", "Environment", "App", "Data", "Workloads", "Workload")


def _short(value: Any) -> Any:
    text = value if isinstance(value, str) else None
    if text is not None and len(text) > _MAX_VALUE_CHARS:
        return text[:_MAX_VALUE_CHARS] + "... (truncated)"
    return value


def _configured_attrs(plan: Plan, change: Change) -> list[str]:
    """Attributes the author wrote in the configuration (not provider defaults)."""
    resources = plan.raw.get("configuration", {}).get("root_module", {}).get("resources", []) or []
    config = next((r for r in resources if r["address"] == config_address(change.address)), {})
    return sorted(config.get("expressions", {}))


def _changed_values(plan: Plan, change: Change) -> dict[str, Any]:
    """before/after for the attributes a reviewer cares about."""
    if change.kind == "create":
        attrs = [a for a in _configured_attrs(plan, change) if a not in _HIDDEN_ATTRS]
        return {a: _short("(known after apply)" if change.is_unknown(a) else change.after.get(a)) for a in attrs}
    if change.kind == "delete":
        return {"tags": change.before.get("tags")}
    attrs = [a for a in change.changed_attrs if a not in _HIDDEN_ATTRS]
    if change.kind == "replace":
        forced = {".".join(map(str, p)) for p in change.replace_paths}
        attrs = [a for a in attrs if a in forced or not change.is_unknown(a)]
    return {
        a: {
            "before": _short(change.before.get(a)),
            "after": "(known after apply)" if change.is_unknown(a) else _short(change.after.get(a)),
        }
        for a in attrs
    }


def _dependents(plan: Plan, address: str) -> list[str]:
    """Config addresses that reference this resource, up to two hops away."""
    first = sorted(plan.dependents_index.get(config_address(address), set()))
    second = sorted({d for f in first for d in plan.dependents_index.get(f, set())} - set(first) - {address})
    return (first + second)[:_MAX_DEPENDENTS]


def _network(plan: Plan, change: Change) -> dict[str, Any]:
    """Subnets and tools behind a route table, for routing changes."""
    route_table = change.before.get("route_table_id") or change.after.get("route_table_id")
    if change.type not in ("aws_route", "aws_route_table", "aws_route_table_association") or not route_table:
        return {}
    subnets = [{"id": sid, **{k: v for k, v in tags.items() if k in _TAG_KEYS}}
               for sid, tags in plan.subnets_of_route_table(route_table)]
    rt_values = next((v for _, v in plan.state_resources("aws_route_table") if v.get("id") == route_table), {})
    groups = [{"name": g.get("name"), "description": g.get("description")}
              for g in plan.security_groups_in_vpc(rt_values.get("vpc_id", ""))
              if g.get("name") != "default"]
    return {"route_table": route_table, "subnets_using_it": subnets, "security_groups_in_vpc": groups}


def build_context(plan: Plan, findings: list[Finding], level: Level | None) -> dict[str, Any]:
    changes = []
    for change in plan.managed_changes:
        entry: dict[str, Any] = {
            "address": change.address,
            "action": change.kind,
            "environment": env_of(change),
            "tags": {k: v for k, v in change.tags().items() if k in _TAG_KEYS},
            "changed": _changed_values(plan, change),
            "depended_on_by": _dependents(plan, change.address),
        }
        if change.replace_paths:
            entry["replaced_because"] = [".".join(map(str, p)) for p in change.replace_paths]
        network = _network(plan, change)
        if network:
            entry["network"] = network
        changes.append(entry)
    return {
        "risk_level": level.label if level else "NONE",
        "counts": plan.counts(),
        "findings": [
            {"level": f.level.label, "rule": f.rule_id, "address": f.address, "title": f.title, "why": f.why}
            for f in findings
        ],
        "changes": changes,
    }
