# =============================================================================
# GitHub Actions -> AWS without access keys (OIDC).
#
# Each workflow run gets a short-lived token signed by GitHub. AWS checks the
# signature and the token claims (which repo, which event) and, if they match
# the trust policy below, hands out temporary credentials for acme-ci-plan.
# =============================================================================

locals {
  # Repos created after 2026-07-15 get IMMUTABLE subject claims that embed the
  # numeric owner/repo IDs, so a deleted-and-recreated repo with the same name
  # can't assume this role. The workflow's debug step prints the real `sub`;
  # if it differs from this value, set var.github_oidc_subject_override.
  github_oidc_subject = coalesce(
    var.github_oidc_subject_override,
    "repo:${var.github_owner}@${var.github_owner_id}/${var.github_repo}@${var.github_repo_id}:pull_request",
  )
}

# aws_iam_openid_connect_provider: registers GitHub Actions as a trusted
# identity provider in this account. Only ONE provider per URL can exist per
# account: if you already have one, import it instead (see README).
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # thumbprint_list is optional: IAM validates GitHub's certificate on its own.
}

# Trust policy: ONLY pull_request runs of this exact repository can assume the role.
data "aws_iam_policy_document" "ci_plan_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.github_oidc_subject]
    }
  }
}

resource "aws_iam_role" "ci_plan" {
  name                 = "acme-ci-plan"
  description          = "Read-only role for PlanGuard: terraform plan on pull requests."
  assume_role_policy   = data.aws_iam_policy_document.ci_plan_trust.json
  max_session_duration = 3600
}

# ReadOnlyAccess covers every Describe/Get/List call that `terraform plan` makes.
# With it, CI physically cannot create, change or delete anything.
resource "aws_iam_role_policy_attachment" "ci_plan_readonly" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ...but ReadOnlyAccess can also read DATA (any S3 object, logs, parameters).
# An explicit Deny always wins over an Allow, so CI can read the infra state
# and nothing else that lives in this account.
data "aws_iam_policy_document" "ci_plan_deny_data" {
  statement {
    sid           = "DenyObjectReadsExceptInfraState"
    effect        = "Deny"
    actions       = ["s3:GetObject", "s3:GetObjectVersion"]
    not_resources = ["${aws_s3_bucket.state.arn}/${var.infra_state_key}"]
  }

  statement {
    sid    = "DenyDataPlaneReads"
    effect = "Deny"
    actions = [
      "logs:GetLogEvents",
      "logs:FilterLogEvents",
      "logs:StartQuery",
      "logs:GetQueryResults",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "secretsmanager:GetSecretValue",
      "dynamodb:GetItem",
      "dynamodb:BatchGetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ci_plan_deny_data" {
  name   = "deny-data-reads"
  role   = aws_iam_role.ci_plan.id
  policy = data.aws_iam_policy_document.ci_plan_deny_data.json
}
