provider "aws" {
  region = var.region

  # Laptop: "acme-sandbox" (exported by scripts/sandbox.sh as TF_VAR_aws_profile).
  # CI: null, so the credentials come from the OIDC role in the environment.
  profile = var.aws_profile

  # Terraform refuses to run against any account other than the sandbox.
  allowed_account_ids = [var.sandbox_account_id]

  default_tags {
    tags = {
      Project   = "acme-health"
      ManagedBy = "terraform"
      Owner     = "planguard-hackathon"
    }
  }
}
