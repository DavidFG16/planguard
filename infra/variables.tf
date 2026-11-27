variable "sandbox_account_id" {
  description = "PERSONAL AWS account ID. Laptop: exported by scripts/sandbox.sh. CI: repository secret."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.sandbox_account_id))
    error_message = "The sandbox_account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_profile" {
  description = "AWS CLI profile. Null in CI, where credentials come from OIDC."
  type        = string
  default     = null
}

variable "region" {
  description = "AWS region of the sandbox."
  type        = string
  default     = "us-east-1"
}
