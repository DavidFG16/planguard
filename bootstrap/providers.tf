provider "aws" {
  region = var.region

  # Hardcoded on purpose: bootstrap only ever runs from your laptop, through
  # scripts/sandbox.sh, which points the AWS CLI/SDK at an isolated config file
  # that only contains this profile. Without the wrapper this fails with
  # "profile not found" instead of silently using other credentials.
  profile = "acme-sandbox"

  # allowed_account_ids: Terraform refuses to run if the credentials belong to
  # any account other than your personal sandbox.
  allowed_account_ids = [var.sandbox_account_id]

  default_tags {
    tags = {
      Project   = "acme-health"
      ManagedBy = "terraform"
      Owner     = "planguard-hackathon"
      Stack     = "bootstrap"
    }
  }
}
