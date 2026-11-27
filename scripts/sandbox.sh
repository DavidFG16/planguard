#!/usr/bin/env bash
# =============================================================================
# sandbox.sh — the ONLY entry point for aws/terraform commands in this repo.
#
# Why: this laptop also holds other AWS credentials (~/.aws/credentials
# [default]). This wrapper makes them unreachable:
#   1. Refuses to run if the shell carries any AWS_* credential/profile variable.
#   2. Points the AWS CLI and Terraform at an isolated config file that only
#      knows the personal "acme-sandbox" profile, and at /dev/null for the
#      shared credentials file.
#   3. Verifies with STS that the credentials belong to the expected personal
#      account before running anything.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly SANDBOX_PROFILE="acme-sandbox"
readonly SANDBOX_REGION="us-east-1"
readonly SANDBOX_CONFIG_FILE="${HOME}/.aws/acme-sandbox-config"
readonly ENV_FILE="${REPO_ROOT}/.sandbox.env"

# Resource types that cost money even when idle. The base stack must never create them.
readonly FORBIDDEN_TYPES='[
  "aws_nat_gateway", "aws_eip", "aws_instance", "aws_db_instance", "aws_rds_cluster",
  "aws_lb", "aws_kms_key", "aws_secretsmanager_secret", "aws_route53_zone",
  "aws_ec2_client_vpn_endpoint", "aws_ecs_service", "aws_elasticache_cluster",
  "aws_opensearch_domain"
]'

die()  { printf '\n✋ %s\n' "$*" >&2; exit 1; }
info() { printf '› %s\n' "$*" >&2; }

usage() {
  cat >&2 <<'EOF'
Usage: scripts/sandbox.sh <command> [args]

  login                     Sign in to the personal sandbox (aws login --remote: you open the URL)
  whoami                    Show and verify the sandbox identity
  check                     Offline fmt + validate of bootstrap/ and infra/ (no AWS calls)
  tf <terraform args>       Run terraform against the sandbox, e.g.: tf -chdir=infra plan
  aws <aws-cli args>        Run the AWS CLI against the sandbox, e.g.: aws s3 ls
  apply <bootstrap|infra>   plan -> cost guard -> confirmation -> apply
EOF
  exit 2
}

# 1. Refuse to run if the shell carries ANY AWS identity (it could be someone else's).
guard_env() {
  local v
  for v in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN \
           AWS_PROFILE AWS_DEFAULT_PROFILE AWS_CONFIG_FILE AWS_SHARED_CREDENTIALS_FILE \
           AWS_ROLE_ARN AWS_WEB_IDENTITY_TOKEN_FILE \
           AWS_CONTAINER_CREDENTIALS_FULL_URI AWS_CONTAINER_CREDENTIALS_RELATIVE_URI; do
    if [[ -n "${!v:-}" ]]; then
      die "$v is set in this shell, and it could point at non-sandbox credentials.
   Open a clean terminal (or run: unset $v) and try again."
    fi
  done
}

# 2. Point the AWS CLI / SDKs at an isolated config that only knows the sandbox profile.
isolate_env() {
  export AWS_CONFIG_FILE="$SANDBOX_CONFIG_FILE"
  export AWS_SHARED_CREDENTIALS_FILE=/dev/null
  export AWS_EC2_METADATA_DISABLED=true
  export AWS_PROFILE="$SANDBOX_PROFILE"
  export AWS_REGION="$SANDBOX_REGION"
  export AWS_PAGER=""
  # Share downloaded providers between bootstrap/ and infra/.
  export TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-${HOME}/.terraform.d/plugin-cache}"
  mkdir -p "$TF_PLUGIN_CACHE_DIR"
}

load_env() {
  [[ -f "$ENV_FILE" ]] || die "Missing .sandbox.env. Run: cp .sandbox.env.example .sandbox.env (then fill it in)"
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  [[ "${SANDBOX_ACCOUNT_ID:-}" =~ ^[0-9]{12}$ ]] \
    || die "SANDBOX_ACCOUNT_ID in .sandbox.env must be your 12-digit PERSONAL account ID."
  [[ "$SANDBOX_ACCOUNT_ID" != "000000000000" ]] \
    || die "SANDBOX_ACCOUNT_ID in .sandbox.env still has the placeholder value."
}

# 3. Never run anything unless STS confirms we are in the personal sandbox account.
verify_account() {
  [[ -s "$SANDBOX_CONFIG_FILE" ]] || die "No sandbox AWS config yet. Run: scripts/sandbox.sh login"
  local actual
  if ! actual="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)"; then
    die "Not signed in to the sandbox (or the session expired). Run: scripts/sandbox.sh login"
  fi
  [[ "$actual" == "$SANDBOX_ACCOUNT_ID" ]] \
    || die "Credentials belong to account ${actual}, expected ${SANDBOX_ACCOUNT_ID}. Aborting."
  # Inputs shared by bootstrap/ and infra/ (undeclared TF_VAR_* are ignored).
  export TF_VAR_sandbox_account_id="$SANDBOX_ACCOUNT_ID"
  export TF_VAR_aws_profile="$SANDBOX_PROFILE"
}

cmd_login() {
  load_env # fail fast, before any browser sign-in
  [[ -t 0 ]] || die "login asks you to paste a code. Run it in your own terminal window."
  mkdir -p "$(dirname "$SANDBOX_CONFIG_FILE")"
  if [[ ! -s "$SANDBOX_CONFIG_FILE" ]]; then
    ( umask 077 && printf '[profile %s]\nregion = %s\n' "$SANDBOX_PROFILE" "$SANDBOX_REGION" > "$SANDBOX_CONFIG_FILE" )
    info "Created isolated AWS config: $SANDBOX_CONFIG_FILE"
  fi
  # --remote: the CLI prints the sign-in URL instead of opening the DEFAULT browser,
  # which may hold other console sessions. You choose the browser profile.
  cat >&2 <<'EOF'
› 1. Copy the URL printed below.
  2. Open it in a SEPARATE browser profile that only knows your PERSONAL AWS account
     (the account picker lists every console session that browser is signed in to).
  3. Sign in as the IAM user "sandbox-admin" (not root) and paste the code back here.
EOF
  aws login --remote --profile "$SANDBOX_PROFILE"
  verify_account
  info "✅ Signed in to sandbox account ${SANDBOX_ACCOUNT_ID}"
}

cmd_whoami() {
  load_env
  verify_account
  aws sts get-caller-identity --output table
  info "✅ Sandbox account verified (${SANDBOX_ACCOUNT_ID}, profile ${SANDBOX_PROFILE})"
}

# Offline on purpose: no credentials at all, so nothing here can reach AWS.
cmd_check() {
  export AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null
  unset AWS_PROFILE
  local dir
  info "terraform fmt -check"
  terraform -chdir="$REPO_ROOT" fmt -check -recursive -diff
  for dir in bootstrap infra; do
    info "terraform validate (${dir}/)"
    terraform -chdir="${REPO_ROOT}/${dir}" init -backend=false -input=false -no-color >/dev/null
    terraform -chdir="${REPO_ROOT}/${dir}" validate -no-color
  done
  info "✅ fmt + validate passed"
}

cmd_tf()  { load_env; verify_account; exec terraform "$@"; }
cmd_aws() { load_env; verify_account; exec aws "$@"; }

cmd_apply() {
  local dir="${1:-}" paid answer
  [[ "$dir" == "bootstrap" || "$dir" == "infra" ]] || die "Usage: scripts/sandbox.sh apply <bootstrap|infra>"
  # A human reads the plan and types 'yes'. No piping, no auto-approve.
  [[ -t 0 ]] || die "apply waits for you to type 'yes'. Run it in your own terminal window."
  load_env
  verify_account
  cd "${REPO_ROOT}/${dir}"
  rm -f tfplan tfplan.json

  terraform plan -input=false -out=tfplan
  terraform show -json tfplan > tfplan.json

  # Cost guard: block any plan that CREATES a paid resource type.
  paid="$(jq -r --argjson forbidden "$FORBIDDEN_TYPES" '
    .resource_changes[]?
    | select(.change.actions | index("create"))
    | select((.type as $t | $forbidden | index($t))
             or (.type == "aws_vpc_endpoint" and .change.after.vpc_endpoint_type == "Interface"))
    | "   - \(.address) (\(.type))"' tfplan.json)"
  rm -f tfplan.json
  if [[ -n "$paid" ]]; then
    rm -f tfplan
    die "Cost guard: this plan creates resources that cost money in the sandbox:
${paid}
   Nothing was applied."
  fi
  info "Cost guard passed: no paid resource types in this plan."

  read -r -p "Apply this plan to sandbox account ${SANDBOX_ACCOUNT_ID}? Type 'yes' to continue: " answer
  if [[ "$answer" != "yes" ]]; then
    rm -f tfplan
    die "Aborted. Nothing was applied."
  fi
  terraform apply -input=false tfplan
  rm -f tfplan
}

main() {
  local cmd="${1:-}"
  [[ $# -gt 0 ]] && shift
  case "$cmd" in
    login|whoami|check|tf|aws|apply) ;;
    *) usage ;;
  esac
  guard_env
  isolate_env
  case "$cmd" in
    login)  cmd_login ;;
    whoami) cmd_whoami ;;
    check)  cmd_check ;;
    tf)     cmd_tf "$@" ;;
    aws)    cmd_aws "$@" ;;
    apply)  cmd_apply "$@" ;;
  esac
}

main "$@"
