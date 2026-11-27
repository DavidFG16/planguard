"""Render the PlanGuard pull request comment (Markdown)."""

from __future__ import annotations

from .explain import MODEL_LABEL, ExplainResult
from .plan import Plan, sanitize
from .rules import Finding, Level

MARKER = "<!-- planguard -->"
HEADLINES = {
    Level.CRITICAL: "⛔ CRITICAL · merge blocked",
    Level.HIGH: "🔴 HIGH · needs a careful review",
    Level.MEDIUM: "🟡 MEDIUM · review the flagged changes",
    Level.LOW: "🟢 LOW · looks safe",
}
_ICONS = {"create": "➕", "update": "🔧", "replace": "♻️", "delete": "🗑️"}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _footer(explained: bool, commit: str) -> str:
    source = MODEL_LABEL if explained else "not available"
    at = f" · commit <code>{commit[:7]}</code>" if commit else ""
    return (
        f"<sub>Risk level: deterministic rules (<code>planguard/rules.py</code>), so the AI cannot change it. "
        f"Explanation: {source}{at}.</sub>"
    )


def render(
    plan: Plan,
    findings: list[Finding],
    level: Level | None,
    result: ExplainResult | None,
    *,
    commit: str = "",
    account_ids: tuple[str, ...] = (),
) -> str:
    lines = [MARKER]
    if level is None:
        lines += [
            "## 🛡️ PlanGuard · ✅ No infrastructure changes",
            "",
            "This pull request does not change any infrastructure.",
            "",
            _footer(False, commit),
        ]
        return sanitize("\n".join(lines), account_ids) + "\n"

    explanation = result.explanation if result else None
    lines += [f"## 🛡️ PlanGuard · {HEADLINES[level]}", ""]
    if explanation:
        lines += [explanation.summary, ""]

    if findings:
        lines += ["| Risk | Rule | Resource | Why |", "|:-:|---|---|---|"]
        for finding in findings:
            lines.append(
                f"| {finding.level.emoji} | `{finding.rule_id}` | `{_cell(finding.address)}` "
                f"| **{_cell(finding.title)}.** {_cell(finding.why)} |"
            )
        lines.append("")

    if explanation:
        if explanation.blast_radius:
            lines += ["### 💥 Blast radius", *[f"- {item}" for item in explanation.blast_radius], ""]
        if explanation.rollback:
            lines += ["### ↩️ Rollback", *[f"{n}. {step}" for n, step in enumerate(explanation.rollback, 1)], ""]
        if explanation.reviewer_checklist:
            lines += ["### ✅ Before you merge", *[f"- [ ] {item}" for item in explanation.reviewer_checklist], ""]
    else:
        note = result.note if result and result.note else "not requested"
        lines += [f"> ℹ️ AI explanation unavailable: {note}. The risk level does not depend on it.", ""]

    counts = " · ".join(f"{_ICONS[kind]} {n} {kind}" for kind, n in plan.counts().items())
    lines += [f"<details><summary>📋 Plan: {counts}</summary>", "", "| Action | Resource |", "|---|---|"]
    lines += [f"| {_ICONS.get(c.kind, '•')} {c.kind} | `{_cell(c.address)}` |" for c in plan.managed_changes]
    lines += ["", "</details>", "", _footer(explanation is not None, commit)]
    return sanitize("\n".join(lines), account_ids) + "\n"
