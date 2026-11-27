#!/usr/bin/env bash
# =============================================================================
# summarize-plan.sh — Wednesday placeholder for the PlanGuard tool.
# Turns `terraform show -json` output into a Markdown PR comment with counts.
#
# Usage: scripts/summarize-plan.sh infra/plan.json > comment.md
# =============================================================================
set -euo pipefail

plan_json="${1:?Usage: summarize-plan.sh <plan.json>}"
[[ -f "$plan_json" ]] || { printf 'No such file: %s\n' "$plan_json" >&2; exit 1; }

jq -r '
  # terraform encodes each change as a list of actions; ["delete","create"] is a replacement.
  def kind:
    if   . == ["create"] then "create"
    elif . == ["update"] then "update"
    elif . == ["delete"] then "delete"
    elif . == ["delete","create"] or . == ["create","delete"] then "replace"
    else empty end;
  def icon: {"create": "➕", "update": "🔧", "replace": "♻️", "delete": "🗑️"}[.];

  [ .resource_changes[]? | {address, kind: (.change.actions | kind)} ] as $changes
  | ($changes | group_by(.kind) | map({key: .[0].kind, value: length}) | from_entries) as $n
  | "<!-- planguard -->",
    "### 🛡️ PlanGuard: plan summary (preview)",
    "",
    "| ➕ create | 🔧 update | ♻️ replace | 🗑️ delete |",
    "|---:|---:|---:|---:|",
    "| \($n.create // 0) | \($n.update // 0) | \($n.replace // 0) | \($n.delete // 0) |",
    "",
    ( if ($changes | length) == 0 then
        "No infrastructure changes. ✅"
      else
        "<details><summary>Resource changes (\($changes | length))</summary>",
        "",
        "| Action | Address |",
        "|---|---|",
        ( $changes[] | "| \(.kind | icon) \(.kind) | `\(.address)` |" ),
        "",
        "</details>"
      end ),
    "",
    "_Risk analysis and AI explanation: coming soon._"
' "$plan_json"
