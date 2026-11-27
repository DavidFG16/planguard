terraform {
  # 1.15+ lets the S3 backend (used by infra/) read `aws login` credentials.
  required_version = ">= 1.15.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.23, < 7.0" # 6.23+ understands `aws login` credentials
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # No backend block on purpose: bootstrap keeps a LOCAL state (gitignored)
  # because it creates the S3 bucket that will hold the state of infra/.
}
