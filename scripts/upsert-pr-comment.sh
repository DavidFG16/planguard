#!/usr/bin/env bash
# =============================================================================
# upsert-pr-comment.sh — creates or updates the single PlanGuard comment on a
# pull request. It finds the bot's previous comment by a hidden marker and
# edits it, so every push updates one comment instead of adding a new one.
#
# Usage (GitHub Actions): scripts/upsert-pr-comment.sh comment.md
# Needs: GH_TOKEN, GITHUB_REPOSITORY, PR_NUMBER
# =============================================================================
set -euo pipefail

body_file="${1:?Usage: upsert-pr-comment.sh <comment.md>}"
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
readonly MARKER='<!-- planguard -->'

if ! grep -qF "$MARKER" "$body_file"; then
  { printf '%s\n' "$MARKER"; cat "$body_file"; } > "${body_file}.tmp"
  mv "${body_file}.tmp" "$body_file"
fi

comment_id="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" \
  --jq ".[] | select(.user.login == \"github-actions[bot]\" and (.body | contains(\"${MARKER}\"))) | .id" \
  | tail -n 1)"

if [[ -n "$comment_id" ]]; then
  gh api --method PATCH "repos/${GITHUB_REPOSITORY}/issues/comments/${comment_id}" \
    -F "body=@${body_file}" >/dev/null
  echo "Updated PlanGuard comment ${comment_id}"
else
  gh api --method POST "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" \
    -F "body=@${body_file}" >/dev/null
  echo "Created PlanGuard comment"
fi
