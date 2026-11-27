#!/usr/bin/env bash
# =============================================================================
# export-fixtures.sh — saves the plan JSON of main and of every scenario/*
# branch as test fixtures for the PlanGuard tool, with the real account ID
# replaced by 123456789012.
#
# Read-only: runs `terraform plan -lock=false` through scripts/sandbox.sh.
# It never applies anything.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly FIXTURES_DIR="${REPO_ROOT}/planguard/tests/fixtures"
readonly FAKE_ACCOUNT_ID="123456789012"
readonly SANDBOX="${REPO_ROOT}/scripts/sandbox.sh"

die() { printf '\n✋ %s\n' "$*" >&2; exit 1; }

cd "$REPO_ROOT"
[[ -f .sandbox.env ]] || die "Missing .sandbox.env"
account_id="$(sed -n 's/^SANDBOX_ACCOUNT_ID=\([0-9]\{12\}\).*$/\1/p' .sandbox.env)"
[[ "$account_id" =~ ^[0-9]{12}$ ]] || die "SANDBOX_ACCOUNT_ID not found in .sandbox.env"

if ! git diff --quiet || ! git diff --cached --quiet; then
  die "You have uncommitted changes. Commit or stash them first."
fi

original_ref="$(git rev-parse --abbrev-ref HEAD)"
tmp_dir="$(mktemp -d)"
cleanup() {
  git checkout -q "$original_ref" 2>/dev/null || true
  rm -f "${REPO_ROOT}/infra/tfplan"
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

# Fixtures are written to a temp dir first, so switching branches never
# collides with fixture files tracked on main.
export_one() {
  local ref="$1" name="$2" out changes
  out="${tmp_dir}/${name}.json"
  printf '› %-32s ' "$name" >&2
  git checkout -q "$ref"
  "$SANDBOX" tf -chdir=infra plan -input=false -lock=false -out=tfplan >/dev/null
  "$SANDBOX" tf -chdir=infra show -json tfplan \
    | sed "s/${account_id}/${FAKE_ACCOUNT_ID}/g" \
    | jq --sort-keys . > "$out"
  rm -f infra/tfplan
  if grep -q "$account_id" "$out"; then
    die "The real account ID is still present in ${name}.json"
  fi
  changes="$(jq '[.resource_changes[]? | select(.change.actions != ["no-op"])] | length' "$out")"
  printf '%s changes\n' "$changes" >&2
}

export_one main 00-main-no-changes

branches="$(git for-each-ref --format='%(refname:short)' 'refs/heads/scenario/*')"
[[ -n "$branches" ]] || die "No scenario/* branches found."
for branch in $branches; do
  export_one "$branch" "${branch#scenario/}"
done

git checkout -q "$original_ref"
mkdir -p "$FIXTURES_DIR"
cp "$tmp_dir"/*.json "$FIXTURES_DIR"/
printf '\n✅ Fixtures written to planguard/tests/fixtures/ (on branch %s)\n' "$original_ref" >&2
