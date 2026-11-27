output "ci_role_arn" {
  description = "Save as GitHub secret AWS_PLAN_ROLE_ARN."
  value       = aws_iam_role.ci_plan.arn
}

output "state_bucket_name" {
  description = "Save as GitHub secret TF_STATE_BUCKET, in .sandbox.env and in infra/backend.hcl."
  value       = aws_s3_bucket.state.bucket
}

output "github_oidc_subject" {
  description = "Exact `sub` the trust policy expects. Compare it with the workflow's debug step."
  value       = local.github_oidc_subject
}
