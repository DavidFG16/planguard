"""Deterministic risk rules. The risk level of a pull request comes only from here.

Each rule is a pure function: (change, plan) -> list[Finding]. No network, no AI,
so every verdict is reproducible and covered by tests on real plan fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .plan import ENV_PRODUCTION, Change, Plan, config_address, deferred_read_source, env_of


class Level(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def emoji(self) -> str:
        return {1: "🟢", 2: "🟡", 3: "🔴", 4: "⛔"}[self.value]

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class Finding:
    level: Level
    rule_id: str
    address: str
    title: str
    why: str


Rule = Callable[[Change, Plan], list[Finding]]

_WORLD = ("0.0.0.0/0", "::/0")
_ADMIN_PORTS = {22: "SSH", 3389: "RDP"}
_POLICY_TYPES = {"aws_iam_role_policy", "aws_iam_policy", "aws_iam_user_policy", "aws_iam_group_policy"}
_NETWORK_TYPES = {
    "aws_vpc", "aws_subnet", "aws_route_table", "aws_route_table_association", "aws_security_group",
    "aws_nat_gateway", "aws_internet_gateway", "aws_eip", "aws_lb", "aws_db_subnet_group",
}
_STATEFUL_TYPES = {
    "aws_s3_bucket", "aws_db_instance", "aws_rds_cluster", "aws_dynamodb_table",
    "aws_efs_file_system", "aws_ebs_volume", "aws_elasticache_cluster",
}
_WRITES = ("create", "update", "replace")


def _is_prod(change: Change) -> bool:
    return env_of(change) == ENV_PRODUCTION


def _statements(policy: Any) -> list[dict[str, Any]]:
    """Statements of a policy JSON string (or [] if unknown or invalid)."""
    if not isinstance(policy, str) or not policy:
        return []
    try:
        doc = json.loads(policy)
    except json.JSONDecodeError:
        return []
    statements = doc.get("Statement", [])
    return [statements] if isinstance(statements, dict) else [s for s in statements if isinstance(s, dict)]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _code_list(items: list[Any]) -> str:
    """`a`, `b`: one code span per value, so Markdown keeps the values apart."""
    return ", ".join(f"`{item}`" for item in items)


def _planned(change: Change, attr: str) -> Any:
    return "(known after apply)" if change.is_unknown(attr) else change.after.get(attr)


# ---------------------------------------------------------------------- network


def default_route_change(change: Change, plan: Plan) -> list[Finding]:
    """The 0.0.0.0/0 route of a route table stops pointing at an internet gateway."""
    if change.type != "aws_route" or change.kind not in ("update", "replace", "delete"):
        return []
    if change.before.get("destination_cidr_block") != "0.0.0.0/0":
        return []
    old_target = change.before.get("gateway_id") or ""
    if not old_target.startswith("igw-"):
        return []
    if change.kind == "update" and "gateway_id" not in change.changed_attrs:
        return []

    route_table = change.before.get("route_table_id", "")
    subnets = plan.subnets_of_route_table(route_table)
    new_target = _new_route_target(change, plan)
    workloads = sorted({w for _, tags in subnets for w in tags.get("Workloads", "").split(",") if w})
    names = ", ".join(tags.get("Name", sid) for sid, tags in subnets) or "its subnets"
    why = (
        f"The default route of `{route_table}` moves from internet gateway `{old_target}` to {new_target}. "
        f"Every subnet that uses this route table ({names}) loses its direct path to the internet"
        + (f"; workloads there: {', '.join(workloads)}." if workloads else ".")
    )
    findings = [Finding(Level.CRITICAL, "default-route-change", change.address,
                        "Default route (0.0.0.0/0) leaves the internet gateway", why)]
    findings += _nat_self_loop(change, plan, {sid for sid, _ in subnets})
    return findings


def _new_route_target(change: Change, plan: Plan) -> str:
    if change.kind == "delete":
        return "nothing (the route is deleted)"
    targets = {"nat_gateway_id": "NAT gateway", "transit_gateway_id": "transit gateway",
               "network_interface_id": "network interface", "vpc_peering_connection_id": "VPC peering connection"}
    for attr, label in targets.items():
        if attr in change.changed_attrs:
            refs = sorted(plan.references(change.address, attr))
            if refs and plan.change(refs[0]) is not None and plan.change(refs[0]).kind == "create":
                return f"{label} `{refs[0]}`, which this pull request creates"
            return f"{label} `{refs[0] if refs else change.after.get(attr) or '(known after apply)'}`"
    return "a different target"


def _nat_self_loop(route: Change, plan: Plan, route_subnet_ids: set[str]) -> list[Finding]:
    """A NAT gateway that sits in one of the subnets whose default route now points at it."""
    nat_refs = plan.references(route.address, "nat_gateway_id")
    findings = []
    for nat in plan.managed_changes:
        referenced = nat.address in nat_refs or config_address(nat.address) in nat_refs
        if nat.type != "aws_nat_gateway" or not referenced:
            continue
        nat_subnet = nat.value("subnet_id")
        if nat_subnet in route_subnet_ids:
            subnet_name = plan.subnet_tags(nat_subnet).get("Name", nat_subnet)
            findings.append(Finding(
                Level.CRITICAL, "nat-self-loop", nat.address,
                "NAT gateway routes to itself",
                f"`{nat.address}` lives in subnet `{subnet_name}`, which uses the same route table. A NAT gateway "
                "needs that subnet's default route to reach an internet gateway; pointing it at the NAT itself "
                "creates a loop, so the NAT and everything behind it have no internet egress.",
            ))
    return findings


def sg_open_to_world(change: Change, plan: Plan) -> list[Finding]:
    """Ingress from 0.0.0.0/0 or ::/0 to SSH, RDP or every port."""
    if change.kind not in _WRITES:
        return []
    rules: list[tuple[Any, Any, Any, list[Any]]] = []  # (protocol, from, to, cidrs)
    after = change.after
    if change.type == "aws_vpc_security_group_ingress_rule":
        rules.append((after.get("ip_protocol"), after.get("from_port"), after.get("to_port"),
                      [after.get("cidr_ipv4"), after.get("cidr_ipv6")]))
    elif change.type == "aws_security_group_rule" and after.get("type") == "ingress":
        rules.append((after.get("protocol"), after.get("from_port"), after.get("to_port"),
                      _as_list(after.get("cidr_blocks")) + _as_list(after.get("ipv6_cidr_blocks"))))
    elif change.type == "aws_security_group":
        for rule in _as_list(after.get("ingress")):
            rules.append((rule.get("protocol"), rule.get("from_port"), rule.get("to_port"),
                          _as_list(rule.get("cidr_blocks")) + _as_list(rule.get("ipv6_cidr_blocks"))))

    findings = []
    for protocol, from_port, to_port, cidrs in rules:
        world = [c for c in cidrs if c in _WORLD]
        if not world:
            continue
        if str(protocol) in ("-1", "all"):
            exposed = "every port"
        else:
            hits = [f"{name} ({port})" for port, name in _ADMIN_PORTS.items()
                    if isinstance(from_port, int) and isinstance(to_port, int) and from_port <= port <= to_port]
            if not hits:
                continue
            exposed = ", ".join(hits)
        findings.append(Finding(
            Level.HIGH, "sg-open-to-world", change.address,
            f"{exposed} open to the internet",
            f"Ingress from {_code_list(world)} to {exposed} on `{after.get('security_group_id') or change.address}`"
            f" ({env_of(change)}). Anyone on the internet can try to connect.",
        ))
    return findings


def replace_network(change: Change, plan: Plan) -> list[Finding]:
    """Network or stateful resources that Terraform must destroy and recreate."""
    if change.kind != "replace" or change.type not in _NETWORK_TYPES | _STATEFUL_TYPES:
        return []
    if change.type in _STATEFUL_TYPES and _is_prod(change):
        return []  # delete_stateful reports it as critical
    paths = [".".join(str(p) for p in path) for path in change.replace_paths]
    diffs = [f"`{p}`: `{change.before.get(p)}` → `{_planned(change, p)}`" for p in paths if p in change.before]
    level = Level.HIGH if _is_prod(change) else Level.MEDIUM
    return [Finding(
        level, "replace-network", change.address,
        f"`{change.type}` is destroyed and recreated",
        f"{_code_list(paths) if paths else 'An attribute'} cannot be updated in place, so Terraform deletes "
        f"and recreates it ({env_of(change)}). {'; '.join(diffs)}".strip(),
    )]


# ------------------------------------------------------------------- data & S3


def delete_stateful(change: Change, plan: Plan) -> list[Finding]:
    """Deleting (or replacing) a resource that holds data."""
    if change.type not in _STATEFUL_TYPES or change.kind not in ("delete", "replace"):
        return []
    if change.kind == "replace" and not _is_prod(change):
        return []  # replace_network covers non-prod replacements
    level = Level.CRITICAL if _is_prod(change) else Level.HIGH
    return [Finding(level, "delete-stateful", change.address, f"`{change.type}` with data is deleted",
                    f"This {change.kind} destroys `{change.address}` ({env_of(change)}) and the data in it.")]


def s3_public_access(change: Change, plan: Plan) -> list[Finding]:
    """S3 Block Public Access settings turned off (or removed)."""
    if change.type != "aws_s3_bucket_public_access_block":
        return []
    flags = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")
    if change.kind == "delete":
        disabled = [f for f in flags if change.before.get(f)]
    elif change.kind in _WRITES:
        disabled = [f for f in flags if change.after.get(f) is False and change.before.get(f) is not False]
    else:
        return []
    if not disabled:
        return []
    level = Level.CRITICAL if _is_prod(change) else Level.HIGH
    bucket = change.value("bucket") or change.address
    return [Finding(
        level, "s3-public-access", change.address, "S3 Block Public Access turned off",
        f"{_code_list(disabled)} → false on bucket `{bucket}` ({env_of(change)}). "
        "This removes the safety net that stops a policy or ACL from making the bucket public.",
    )]


def s3_public_policy(change: Change, plan: Plan) -> list[Finding]:
    """A bucket policy that allows anyone (Principal "*") without conditions."""
    if change.type != "aws_s3_bucket_policy" or change.kind not in _WRITES:
        return []
    findings = []
    for statement in _statements(change.after.get("policy")):
        principal = statement.get("Principal")
        public = principal == "*" or (isinstance(principal, dict) and "*" in _as_list(principal.get("AWS")))
        if statement.get("Effect") == "Allow" and public and not statement.get("Condition"):
            actions = _code_list(_as_list(statement.get("Action")))
            resources = _code_list(_as_list(statement.get("Resource")))
            findings.append(Finding(
                Level.CRITICAL, "s3-public-policy", change.address, "Bucket readable by anyone on the internet",
                f"Statement `{statement.get('Sid', '(no Sid)')}` allows {actions} on {resources} to "
                "`Principal: *` with no condition: no AWS credentials needed.",
            ))
    return findings


def rds_unsafe(change: Change, plan: Plan) -> list[Finding]:
    """Production databases must be encrypted, protected and backed up."""
    if change.type not in ("aws_db_instance", "aws_rds_cluster") or change.kind not in _WRITES:
        return []
    after = change.after
    checks = [
        (after.get("storage_encrypted") is False, "storage is not encrypted (`storage_encrypted = false`)"),
        (after.get("deletion_protection") is False, "no deletion protection (`deletion_protection = false`)"),
        (after.get("skip_final_snapshot") is True, "no final snapshot on delete (`skip_final_snapshot = true`)"),
        (after.get("backup_retention_period") == 0, "automated backups disabled (`backup_retention_period = 0`)"),
        (after.get("publicly_accessible") is True, "reachable from the internet (`publicly_accessible = true`)"),
    ]
    violations = [text for failed, text in checks if failed]
    if not violations:
        return []
    if _is_prod(change):
        level, rule_id = Level.CRITICAL, "rds-unsafe-prod"
    else:
        level, rule_id = Level.MEDIUM, "rds-unsafe"
    summary = "; ".join(violations)
    return [Finding(level, rule_id, change.address, "Database without production safeguards",
                    f"{summary[0].upper()}{summary[1:]}. Environment: {env_of(change)}.")]


# ------------------------------------------------------------------------- IAM


def iam_policy(change: Change, plan: Plan) -> list[Finding]:
    """Wildcard actions, or a policy whose content is only known at apply time."""
    if change.type not in _POLICY_TYPES or change.kind not in _WRITES:
        return []
    if change.is_unknown("policy"):
        source = deferred_read_source(change, plan)
        if source:
            return [Finding(
                Level.LOW, "deferred-read", change.address, "Policy shows as changed, but its content does not change",
                f"Terraform re-reads `{source}` at apply time because something it depends on has pending changes, "
                "and those changes only touch tags. The policy is rebuilt with the same content.",
            )]
        return [Finding(Level.MEDIUM, "iam-unknown-policy", change.address, "IAM policy known only after apply",
                        "The new policy content cannot be reviewed in this plan. Check what it is built from.")]

    findings = []
    for statement in _statements(change.after.get("policy")):
        actions = [a for a in _as_list(statement.get("Action")) if isinstance(a, str)]
        wildcards = [a for a in actions if a == "*" or a.endswith(":*")]
        if statement.get("Effect") == "Allow" and wildcards:
            level = Level.HIGH if _is_prod(change) else Level.MEDIUM
            resources = _code_list(_as_list(statement.get("Resource")))
            findings.append(Finding(
                level, "iam-wildcard", change.address, f"Wildcard permission {_code_list(wildcards)}",
                f"Statement `{statement.get('Sid', '(no Sid)')}` allows every action in {_code_list(wildcards)} "
                f"on {resources} ({env_of(change)}), including deletes and policy changes.",
            ))
    return findings


# ----------------------------------------------------------------------- other


def tags_only(change: Change, plan: Plan) -> list[Finding]:
    if not change.is_tags_only:
        return []
    before = change.before.get("tags") or {}
    after = change.after.get("tags") or {}
    diffs = [f"`{k}`: {before.get(k, '(none)')} → {after.get(k, '(removed)')}"
             for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
    return [Finding(Level.LOW, "tags-only", change.address, "Only tags change",
                    "No behavior change. " + "; ".join(diffs))]


RULES: list[Rule] = [
    default_route_change, sg_open_to_world, replace_network, delete_stateful,
    s3_public_access, s3_public_policy, rds_unsafe, iam_policy, tags_only,
]


def evaluate(plan: Plan) -> list[Finding]:
    """Run every rule on every change; unclassified production changes are medium."""
    findings: list[Finding] = []
    for change in plan.managed_changes:
        found = [f for rule in RULES for f in rule(change, plan)]
        if not found and _is_prod(change):
            found.append(Finding(Level.MEDIUM, "prod-change", change.address, f"Production {change.kind}",
                                 f"`{change.type}` {change.kind} in production with no specific rule match."))
        findings += found
    # Stable sort: within a level, keep plan order and rule order (cause before detail).
    return sorted(findings, key=lambda f: -f.level)


def overall_level(plan: Plan, findings: list[Finding]) -> Level | None:
    """Highest finding level; LOW when there are changes but no findings; None without changes."""
    if findings:
        return max(f.level for f in findings)
    return Level.LOW if plan.managed_changes else None


def exit_code(level: Level | None) -> int:
    """0 lets the check pass (low, medium, high); 2 fails it (critical)."""
    return 2 if level == Level.CRITICAL else 0
