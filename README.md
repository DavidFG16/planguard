# 🛡️ PlanGuard

**An AI reviewer for Terraform pull requests.**

PlanGuard runs `terraform plan` on every pull request. Deterministic rules classify the risk of each change (🟢 low, 🟡 medium, 🔴 high, ⛔ critical). Claude explains in plain language what will change, what else could break (blast radius) and how to roll it back. Critical changes block the merge.

> Built for the Thanksgiving Week Hackathon (Nov 25–27, 2026). Everything runs on personal accounts against a **fictional company, "Acme Health"**. No employer systems, code or data are used.

## How it works

```
Pull request ──► GitHub Actions
                   ├─ OIDC ──► AWS (read-only role, no access keys)
                   ├─ terraform plan  ──►  terraform show -json
                   ├─ PlanGuard
                   │    ├─ rules  → risk level (deterministic, testable)
                   │    └─ Claude → explanation, blast radius, rollback plan
                   └─ one sticky PR comment  +  check fails on ⛔ → merge blocked
```

**Rules decide, AI explains.** The risk level never depends on a model's opinion. The rules are plain code with tests. Claude turns the raw plan into something a reviewer can act on in 30 seconds.

## Repository layout

| Path | What it is |
|---|---|
| `bootstrap/` | One-time setup, applied from a laptop with local state: Terraform state bucket, GitHub OIDC provider, read-only CI role, AWS budget |
| `infra/` | The fictional "Acme Health" stack that pull requests change. One file per app/env, free resource types only |
| `planguard/` | The reviewer tool (Python). `tests/fixtures/` holds real plan JSON from each demo scenario |
| `scripts/sandbox.sh` | The only way to run `aws`/`terraform` here (see Security design) |
| `scripts/export-fixtures.sh` | Saves the plan JSON of every `scenario/*` branch as a sanitized test fixture |
| `.github/workflows/planguard.yml` | The pull request pipeline |

## Security design

- **Credential isolation.** `scripts/sandbox.sh` refuses to run if the shell has any `AWS_*` credential or profile variable. It points the AWS CLI and Terraform at an isolated config file that only contains the `acme-sandbox` profile, with `AWS_SHARED_CREDENTIALS_FILE=/dev/null`, and confirms the account with STS before every command. Providers and the backend also set `allowed_account_ids`.
- **CI is read-only.** GitHub Actions assumes `acme-ci-plan` through OIDC, so there are no stored keys. The trust policy only accepts `pull_request` runs of this repository, matched on its immutable owner and repo IDs. The role has `ReadOnlyAccess` plus an explicit **Deny** on data reads (S3 objects other than the state, logs, parameters and secrets). The plan runs with `-lock=false`, so CI cannot create, change, or read anything private, even if a pull request tries.
- **Cost guard.** `scripts/sandbox.sh apply` blocks any plan that creates a paid resource type: NAT gateways, EIPs, EC2, RDS, load balancers, KMS keys and others. The dangerous demo scenarios exist only as plans and are never applied. An AWS Budget emails at 50% and 100%.
- **Public repo hygiene.** The account ID, role ARN and state bucket are repository **secrets**, so they are masked in logs. No artifacts are uploaded, fixtures are sanitized, and bucket names use a random suffix instead of the account ID.
- **Tamper resistance** (planned for Thursday). The tool runs from the base branch (`base.sha`), so a pull request cannot edit its own reviewer.
- **Known limitation.** A pull request could edit the workflow file itself. In a real repository, protect `.github/` with CODEOWNERS and required reviews.

## Demo scenarios

Each scenario is a **draft** pull request that is never merged and never applied.

| Branch | Change | Expected plan | Risk |
|---|---|---|---|
| `scenario/01-safe-tag` | Add a `CostCenter` tag to the portal-dev bucket | 1 in-place update | 🟢 |
| `scenario/02-iam-s3-wildcard-dev` | The reports-dev task policy becomes `s3:*` | 1 in-place update | 🟡 |
| `scenario/03-ssh-open-prod` | SSH (22) open to `0.0.0.0/0` on the portal-prod security group | 1 create | 🔴 |
| `scenario/04-subnet-cidr-prod` | One-line CIDR change on a prod subnet | Replace (`-/+`) of the subnet and its association | 🔴 |
| `scenario/05-nat-shared-vpc` | NAT gateway inside the shared public subnet, plus the default route pointed at it. The NAT loses its own way out, and so does every tool in the shared VPC | 2 creates + 1 in-place update | ⛔ |
| `scenario/06-public-bucket-prod` | Block Public Access off, plus a public bucket policy on reports-prod | Update + create | ⛔ |
| `scenario/07-rds-prod-unsafe` | Prod database that is unencrypted, has no deletion protection and skips the final snapshot | 2 creates | ⛔ |

## Setup (one time)

Prerequisites: Terraform ≥ 1.15, AWS CLI ≥ 2.32 (for `aws login`), `gh`, `jq`, and a personal AWS account with an IAM user (console + MFA, no access keys).

```bash
# 1. Sandbox identity
cp .sandbox.env.example .sandbox.env            # set SANDBOX_ACCOUNT_ID
scripts/sandbox.sh login                        # in your own terminal; open the URL in a separate browser profile
scripts/sandbox.sh whoami

# 2. Bootstrap: state bucket, OIDC, CI role, budget
cp bootstrap/terraform.tfvars.example bootstrap/terraform.tfvars   # fill in the TODOs
scripts/sandbox.sh tf -chdir=bootstrap init
scripts/sandbox.sh apply bootstrap

# 3. Repository secrets (values never touch the repo)
gh secret set SANDBOX_ACCOUNT_ID                # paste when prompted
gh secret set AWS_PLAN_ROLE_ARN --body "$(scripts/sandbox.sh tf -chdir=bootstrap output -raw ci_role_arn)"
gh secret set TF_STATE_BUCKET   --body "$(scripts/sandbox.sh tf -chdir=bootstrap output -raw state_bucket_name)"

# 4. The fictional stack
cp infra/backend.hcl.example infra/backend.hcl  # fill in the TODOs
scripts/sandbox.sh tf -chdir=infra init -backend-config=backend.hcl
scripts/sandbox.sh apply infra
```

**If the account already has a GitHub OIDC provider:** AWS allows only one per URL. Before applying bootstrap, create `bootstrap/import.tf` with:

```hcl
import {
  to = aws_iam_openid_connect_provider.github
  id = "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
}
```

**If a pull request fails at "Configure AWS credentials":** the OIDC `sub` that GitHub sends does not match the role trust (`scripts/sandbox.sh tf -chdir=bootstrap output github_oidc_subject`). To see the `sub` that GitHub sends, restore the temporary "Debug OIDC subject" step for one run (`git show 1e6609e:.github/workflows/planguard.yml`). Then set `github_oidc_subject_override` in `bootstrap/terraform.tfvars` and apply bootstrap again.

## Everyday commands

```bash
scripts/sandbox.sh check                          # offline fmt + validate, no AWS calls
scripts/sandbox.sh tf -chdir=infra plan
scripts/export-fixtures.sh                        # refresh planguard/tests/fixtures/
```

## Status

- [x] Sandbox infrastructure, read-only CI role and pull request pipeline with plan summary
- [ ] Risk rules and Claude explanation (`planguard/`)
- [ ] Merge blocking on ⛔ (repository ruleset)
- [ ] Demo video
