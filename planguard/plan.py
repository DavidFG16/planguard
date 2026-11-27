"""Load a `terraform show -json` plan and normalize its resource changes.

Only the root module is supported (the demo stack has no child modules).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

PLACEHOLDER_ACCOUNT_ID = "123456789012"

# arn:<partition>:<service>:<region>:<account-id>:<resource>
_ARN_ACCOUNT = re.compile(r"(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)\d{12}(?=:)")
# A resource address at the start of a reference: type.name, data.type.name, optional [key].
_REF_ADDRESS = re.compile(r'^((?:data\.)?[a-z0-9_]+\.[A-Za-z0-9_-]+)(\[(?:"[^"]*"|\d+)\])?')
_INDEX_SUFFIX = re.compile(r'\[(?:"[^"]*"|\d+)\]$')
_TAG_KEYS = frozenset({"tags", "tags_all"})

ENV_PRODUCTION = "production"
ENV_DEVELOPMENT = "development"
ENV_SHARED = "shared"
ENV_UNKNOWN = "unknown"


def sanitize(text: str, account_ids: tuple[str, ...] = ()) -> str:
    """Replace AWS account IDs with a placeholder, because PR comments are public."""
    for account_id in account_ids:
        if account_id:
            text = text.replace(account_id, PLACEHOLDER_ACCOUNT_ID)
    return _ARN_ACCOUNT.sub(rf"\g<1>{PLACEHOLDER_ACCOUNT_ID}", text)


def _kind(actions: list[str]) -> str:
    """Terraform encodes each change as a list of actions; delete+create is a replacement."""
    if sorted(actions) == ["create", "delete"]:
        return "replace"
    if len(actions) == 1:
        return actions[0]  # create | read | update | delete | no-op | forget
    return "+".join(actions)


def _has_unknown(value: Any) -> bool:
    """`after_unknown` marks values known only after apply with `true` leaves."""
    if value is True:
        return True
    if isinstance(value, dict):
        return any(_has_unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_unknown(v) for v in value)
    return False


def config_address(address: str) -> str:
    """aws_subnet.private["prod-b"] -> aws_subnet.private"""
    return _INDEX_SUFFIX.sub("", address)


def _collect_references(node: Any, out: set[str]) -> None:
    """Walk a configuration `expressions` tree and collect resource addresses it references."""
    if isinstance(node, dict):
        for ref in node.get("references", []) or []:
            match = _REF_ADDRESS.match(ref)
            if match and not ref.startswith(("var.", "local.", "each.", "count.", "path.", "module.")):
                out.add(match.group(1) + (match.group(2) or ""))
                out.add(match.group(1))
        for key, value in node.items():
            if key != "references":
                _collect_references(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_references(item, out)


@dataclass(frozen=True)
class Change:
    """One entry of `resource_changes`, with the fields the rules need."""

    address: str
    mode: str  # "managed" | "data"
    type: str
    name: str
    kind: str  # create | update | replace | delete | read | no-op | ...
    before: dict[str, Any]
    after: dict[str, Any]
    after_unknown: dict[str, Any]
    replace_paths: list[list[Any]] = field(default_factory=list)
    action_reason: str | None = None

    @property
    def is_managed(self) -> bool:
        return self.mode == "managed"

    def is_unknown(self, attr: str) -> bool:
        return _has_unknown(self.after_unknown.get(attr))

    @cached_property
    def changed_attrs(self) -> tuple[str, ...]:
        """Top-level attributes whose value changes (or becomes unknown)."""
        if self.kind == "create":
            keys = {k for k, v in self.after.items() if v not in (None, "", [], {})}
            keys |= {k for k in self.after_unknown if self.is_unknown(k)}
        elif self.kind == "delete":
            keys = {k for k, v in self.before.items() if v not in (None, "", [], {})}
        else:
            keys = {
                k
                for k in set(self.before) | set(self.after) | set(self.after_unknown)
                if self.is_unknown(k) or self.before.get(k) != self.after.get(k)
            }
        return tuple(sorted(keys))

    @property
    def is_tags_only(self) -> bool:
        return self.kind == "update" and bool(self.changed_attrs) and set(self.changed_attrs) <= _TAG_KEYS

    def value(self, attr: str) -> Any:
        """The planned value, or the current one for deletes."""
        return (self.before if self.kind == "delete" else self.after).get(attr)

    def tags(self) -> dict[str, str]:
        for source in (self.after, self.before):
            tags = source.get("tags_all") or source.get("tags")
            if tags:
                return dict(tags)
        return {}


@dataclass
class Plan:
    """A parsed plan: managed changes plus the lookups the rules and the context need."""

    raw: dict[str, Any]
    changes: list[Change]

    @classmethod
    def load(cls, path: str | Path) -> Plan:
        raw = json.loads(Path(path).read_text())
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Plan:
        changes = []
        for rc in raw.get("resource_changes", []) or []:
            change = rc.get("change", {})
            changes.append(
                Change(
                    address=rc["address"],
                    mode=rc.get("mode", "managed"),
                    type=rc["type"],
                    name=rc.get("name", ""),
                    kind=_kind(change.get("actions", ["no-op"])),
                    before=change.get("before") or {},
                    after=change.get("after") or {},
                    after_unknown=change.get("after_unknown") or {},
                    replace_paths=change.get("replace_paths") or [],
                    action_reason=rc.get("action_reason"),
                )
            )
        return cls(raw=raw, changes=changes)

    # ------------------------------------------------------------------ changes

    @property
    def managed_changes(self) -> list[Change]:
        """Managed resources that change (no-ops and data reads excluded)."""
        return [c for c in self.changes if c.is_managed and c.kind not in ("no-op", "read")]

    def change(self, address: str) -> Change | None:
        return next((c for c in self.changes if c.address == address), None)

    def changes_for(self, config_addr: str) -> list[Change]:
        """All instances of a config address, e.g. every aws_subnet.private[...]"""
        return [c for c in self.changes if config_address(c.address) == config_addr]

    def counts(self) -> dict[str, int]:
        counts = {"create": 0, "update": 0, "replace": 0, "delete": 0}
        for change in self.managed_changes:
            if change.kind in counts:
                counts[change.kind] += 1
        return counts

    # ------------------------------------------------------------ configuration

    @cached_property
    def _config_resources(self) -> dict[str, dict[str, Any]]:
        resources = self.raw.get("configuration", {}).get("root_module", {}).get("resources", []) or []
        return {r["address"]: r for r in resources}

    def references(self, address: str, attr: str | None = None) -> set[str]:
        """Resource addresses referenced by a resource's configuration (or by one attribute)."""
        resource = self._config_resources.get(config_address(address), {})
        expressions = resource.get("expressions", {})
        node = expressions.get(attr, {}) if attr else [expressions, resource.get("for_each_expression", {})]
        out: set[str] = set()
        _collect_references(node, out)
        out.discard(config_address(address))
        return out

    @cached_property
    def dependents_index(self) -> dict[str, set[str]]:
        """Reverse references: config address -> config addresses that reference it."""
        index: dict[str, set[str]] = {}
        for addr in self._config_resources:
            for ref in self.references(addr):
                index.setdefault(config_address(ref), set()).add(addr)
        return index

    # -------------------------------------------------------------------- state

    @cached_property
    def _state(self) -> dict[str, dict[str, Any]]:
        """Current values (prior_state) overlaid with planned values, by resource address."""
        state: dict[str, dict[str, Any]] = {}
        for section in ("prior_state", "planned_values"):
            root = self.raw.get(section, {}) or {}
            root = root.get("values", root).get("root_module", {})
            for resource in root.get("resources", []) or []:
                state.setdefault(resource["address"], {}).update(
                    {"type": resource.get("type"), "values": resource.get("values") or {}}
                )
        return state

    def state_values(self, address: str) -> dict[str, Any]:
        return self._state.get(address, {}).get("values", {})

    def state_resources(self, resource_type: str) -> list[tuple[str, dict[str, Any]]]:
        return [(a, r.get("values", {})) for a, r in self._state.items() if r.get("type") == resource_type]

    def subnet_tags(self, subnet_id: str) -> dict[str, str]:
        subnet = next((v for _, v in self.state_resources("aws_subnet") if v.get("id") == subnet_id), {})
        return dict(subnet.get("tags") or {})

    def subnets_of_route_table(self, route_table_id: str) -> list[tuple[str, dict[str, str]]]:
        """(subnet_id, subnet tags) for every subnet associated with a route table."""
        subnet_ids = sorted(
            values["subnet_id"]
            for _, values in self.state_resources("aws_route_table_association")
            if route_table_id and values.get("route_table_id") == route_table_id and values.get("subnet_id")
        )
        return [(sid, self.subnet_tags(sid)) for sid in subnet_ids]

    def security_groups_in_vpc(self, vpc_id: str) -> list[dict[str, Any]]:
        return [v for _, v in self.state_resources("aws_security_group") if vpc_id and v.get("vpc_id") == vpc_id]


def env_of(change: Change) -> str:
    """Environment from the Environment tag, falling back to the address naming."""
    raw = change.tags().get("Environment", "").lower()
    if raw in ("production", "prod"):
        return ENV_PRODUCTION
    if raw in ("development", "dev"):
        return ENV_DEVELOPMENT
    if raw == "shared":
        return ENV_SHARED
    tokens = set(re.split(r"[^a-z0-9]+", change.address.lower()))
    if tokens & {"prod", "production"}:
        return ENV_PRODUCTION
    if tokens & {"dev", "development"}:
        return ENV_DEVELOPMENT
    if "shared" in tokens:
        return ENV_SHARED
    return ENV_UNKNOWN


def deferred_read_source(change: Change, plan: Plan, attr: str = "policy") -> str | None:
    """Return the data source that makes `attr` unknown only because its read is deferred.

    Terraform defers a data source read to apply time when it depends on a resource
    with pending changes ("read_because_dependency_pending"). Anything built from that
    data source shows as "(known after apply)", even if its content will not change.
    That is noise when every upstream change only touches tags.
    """
    if not change.is_unknown(attr):
        return None
    for ref in sorted(plan.references(change.address, attr)):
        if not ref.startswith("data."):
            continue
        data = plan.change(ref)
        if data is None or data.action_reason != "read_because_dependency_pending":
            continue
        upstream = [c for r in plan.references(ref) for c in plan.changes_for(config_address(r))]
        pending = [c for c in upstream if c.is_managed and c.kind not in ("no-op", "read")]
        if pending and all(c.is_tags_only for c in pending):
            return ref
    return None
