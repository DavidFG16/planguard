terraform {
  # Partial configuration: bucket, profile and allowed_account_ids live in
  # backend.hcl (gitignored on your laptop, generated from secrets in CI):
  #   scripts/sandbox.sh tf -chdir=infra init -backend-config=backend.hcl
  backend "s3" {
    key          = "infra/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true # native S3 locking (Terraform 1.11+): no DynamoDB table needed
  }
}
