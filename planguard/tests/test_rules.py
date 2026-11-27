"""Every demo scenario must get exactly the verdict documented in the README."""

from __future__ import annotations

import pytest

from planguard.rules import Level, evaluate, exit_code, overall_level

EXPECTED = [
    # fixture, overall level, rule ids that must fire (exactly)
    ("00-main-no-changes", None, set()),
    ("01-safe-tag", Level.LOW, {"tags-only", "deferred-read"}),
    ("02-iam-s3-wildcard-dev", Level.MEDIUM, {"iam-wildcard"}),
    ("03-ssh-open-prod", Level.HIGH, {"sg-open-to-world"}),
    ("04-subnet-cidr-prod", Level.HIGH, {"replace-network"}),
    ("05-nat-shared-vpc", Level.CRITICAL, {"default-route-change", "nat-self-loop"}),
    ("06-public-bucket-prod", Level.CRITICAL, {"s3-public-access", "s3-public-policy"}),
    ("07-rds-prod-unsafe", Level.CRITICAL, {"rds-unsafe-prod", "prod-change"}),
]


@pytest.mark.parametrize(("fixture", "level", "rule_ids"), EXPECTED)
def test_scenario_verdict(load_plan, fixture, level, rule_ids):
    plan = load_plan(fixture)
    findings = evaluate(plan)
    assert {f.rule_id for f in findings} == rule_ids
    assert overall_level(plan, findings) == level


@pytest.mark.parametrize(("fixture", "level", "_"), EXPECTED)
def test_only_critical_fails_the_check(load_plan, fixture, level, _):
    assert exit_code(level) == (2 if level == Level.CRITICAL else 0)


def test_findings_are_sorted_most_severe_first(load_plan):
    findings = evaluate(load_plan("07-rds-prod-unsafe"))
    assert [f.level for f in findings] == sorted((f.level for f in findings), reverse=True)


def test_nat_self_loop_names_the_route_table_subnets(load_plan):
    findings = {f.rule_id: f for f in evaluate(load_plan("05-nat-shared-vpc"))}
    route = findings["default-route-change"]
    assert route.address == "aws_route.shared_public_default"
    assert "acme-shared-public-a" in route.why and "acme-shared-public-b" in route.why
    assert "ci-runner" in route.why and "vpn" in route.why and "bi-dashboard" in route.why
    assert findings["nat-self-loop"].address == "aws_nat_gateway.shared"


def test_public_bucket_lists_the_disabled_flags(load_plan):
    findings = {f.rule_id: f for f in evaluate(load_plan("06-public-bucket-prod"))}
    why = findings["s3-public-access"].why
    assert "`block_public_policy`, `restrict_public_buckets` → false" in why  # one code span per flag
    assert "block_public_acls" not in why  # it stays true in the scenario


def test_unsafe_database_lists_every_violation(load_plan):
    finding = next(f for f in evaluate(load_plan("07-rds-prod-unsafe")) if f.rule_id == "rds-unsafe-prod")
    for attr in ("storage_encrypted", "deletion_protection", "skip_final_snapshot"):
        assert attr in finding.why
    assert finding.why.startswith("Storage is not encrypted") and finding.why.endswith("Environment: production.")


def test_subnet_replacement_explains_the_forcing_attribute(load_plan):
    finding = next(f for f in evaluate(load_plan("04-subnet-cidr-prod")) if f.address.startswith("aws_subnet."))
    assert "cidr_block" in finding.why
    assert "10.30.2.0/24" in finding.why and "10.30.2.0/23" in finding.why
