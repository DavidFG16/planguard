from __future__ import annotations

import re

import pytest

from planguard.explain import ExplainResult, Explanation
from planguard.render import MARKER, render
from planguard.rules import Finding, Level, evaluate, overall_level


def comment_for(load_plan, fixture, result=None, **kwargs):
    plan = load_plan(fixture)
    findings = evaluate(plan)
    return render(plan, findings, overall_level(plan, findings), result, **kwargs)


@pytest.mark.parametrize(
    ("fixture", "headline"),
    [
        ("00-main-no-changes", "✅ No infrastructure changes"),
        ("01-safe-tag", "🟢 LOW"),
        ("02-iam-s3-wildcard-dev", "🟡 MEDIUM"),
        ("03-ssh-open-prod", "🔴 HIGH"),
        ("05-nat-shared-vpc", "⛔ CRITICAL · merge blocked"),
    ],
)
def test_marker_and_headline(load_plan, fixture, headline):
    comment = comment_for(load_plan, fixture)
    assert comment.splitlines()[0] == MARKER
    assert headline in comment.splitlines()[1]


def test_rules_only_comment_says_why_there_is_no_ai(load_plan):
    comment = comment_for(load_plan, "06-public-bucket-prod", ExplainResult(None, "offline mode"))
    assert "AI explanation unavailable: offline mode" in comment
    assert "`s3-public-policy`" in comment and "`s3-public-access`" in comment


def test_explanation_sections(load_plan):
    explanation = Explanation(
        summary="Makes the exports bucket public.",
        blast_radius=["Every export becomes downloadable"],
        rollback=["Re-enable Block Public Access", "Delete the bucket policy"],
        reviewer_checklist=["Is a presigned URL enough?"],
    )
    comment = comment_for(load_plan, "06-public-bucket-prod", ExplainResult(explanation))
    assert "Makes the exports bucket public." in comment
    assert "### 💥 Blast radius" in comment and "1. Re-enable Block Public Access" in comment
    assert "- [ ] Is a presigned URL enough?" in comment
    assert "AI explanation unavailable" not in comment


def test_no_account_id_in_the_public_comment(load_plan):
    plan = load_plan("03-ssh-open-prod")
    leak = Finding(Level.HIGH, "test", "x", "t", "arn:aws:iam::987654321098:role/x and 555555555555")
    comment = render(plan, [leak], Level.HIGH, None, account_ids=("555555555555",))
    assert not re.search(r"987654321098|555555555555", comment)


def test_table_cells_are_escaped(load_plan):
    plan = load_plan("03-ssh-open-prod")
    finding = Finding(Level.HIGH, "test", "x", "a | b", "line one\nline two")
    comment = render(plan, [finding], Level.HIGH, None)
    assert "a \\| b" in comment and "line one line two" in comment
