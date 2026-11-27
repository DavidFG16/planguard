from __future__ import annotations

from planguard.plan import (
    ENV_DEVELOPMENT, ENV_PRODUCTION, ENV_SHARED, PLACEHOLDER_ACCOUNT_ID, Plan, deferred_read_source, env_of, sanitize,
)


def test_replacement_counts_as_replace(load_plan):
    assert load_plan("04-subnet-cidr-prod").counts() == {"create": 0, "update": 0, "replace": 2, "delete": 0}


def test_no_op_plan_has_no_managed_changes(load_plan):
    assert load_plan("00-main-no-changes").managed_changes == []


def test_tag_change_is_tags_only(load_plan):
    bucket = load_plan("01-safe-tag").change("aws_s3_bucket.portal_dev_data")
    assert bucket.is_tags_only


def test_deferred_read_is_detected_only_when_upstream_is_tags_only(load_plan):
    plan = load_plan("01-safe-tag")
    policy = plan.change("aws_iam_role_policy.portal_dev_task")
    assert deferred_read_source(policy, plan) == "data.aws_iam_policy_document.portal_dev_task"

    # Same plan, but the upstream bucket change is no longer tags-only.
    raw = plan.raw
    for rc in raw["resource_changes"]:
        if rc["address"] == "aws_s3_bucket.portal_dev_data":
            rc["change"]["after"]["force_destroy"] = not rc["change"]["before"].get("force_destroy", False)
    mutated = Plan.from_dict(raw)
    assert deferred_read_source(mutated.change("aws_iam_role_policy.portal_dev_task"), mutated) is None


def test_environment_comes_from_tags_then_address(load_plan):
    assert env_of(load_plan("04-subnet-cidr-prod").change('aws_subnet.private["prod-b"]')) == ENV_PRODUCTION
    # Route table associations have no tags: the address decides.
    assert env_of(load_plan("04-subnet-cidr-prod").change('aws_route_table_association.private["prod-b"]')) == ENV_PRODUCTION
    assert env_of(load_plan("02-iam-s3-wildcard-dev").change("aws_iam_role_policy.reports_dev_task")) == ENV_DEVELOPMENT
    assert env_of(load_plan("05-nat-shared-vpc").change("aws_route.shared_public_default")) == ENV_SHARED


def test_references_resolve_resource_addresses(load_plan):
    plan = load_plan("05-nat-shared-vpc")
    assert plan.references("aws_route.shared_public_default", "nat_gateway_id") == {"aws_nat_gateway.shared"}
    assert "aws_route_table_association.shared_public" in plan.dependents_index["aws_route_table.shared_public"]


def test_sanitize_replaces_account_ids():
    text = 'arn:aws:iam::987654321098:role/x arn:aws:s3:::bucket owner 555555555555'
    clean = sanitize(text, account_ids=("555555555555",))
    assert "987654321098" not in clean and "555555555555" not in clean
    assert clean.count(PLACEHOLDER_ACCOUNT_ID) == 2
    assert "arn:aws:s3:::bucket" in clean
