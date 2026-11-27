variable "sandbox_account_id" {
  description = "Your PERSONAL AWS account ID. Exported by scripts/sandbox.sh from .sandbox.env."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.sandbox_account_id))
    error_message = "The sandbox_account_id must be a 12-digit AWS account ID."
  }
}

variable "region" {
  description = "AWS region of the sandbox."
  type        = string
  default     = "us-east-1"
}

variable "github_owner" {
  description = "GitHub user that owns the PlanGuard repository."
  type        = string
}

variable "github_owner_id" {
  description = "Numeric ID of the owner: gh api repos/OWNER/REPO --jq .owner.id"
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "The github_owner_id must be numeric."
  }
}

variable "github_repo" {
  description = "Repository name, without the owner."
  type        = string
  default     = "planguard"
}

variable "github_repo_id" {
  description = "Numeric ID of the repository: gh api repos/OWNER/REPO --jq .id"
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repo_id))
    error_message = "The github_repo_id must be numeric."
  }
}

variable "github_oidc_subject_override" {
  description = "Set ONLY if the workflow's debug step prints a different OIDC `sub` than the output github_oidc_subject."
  type        = string
  default     = null
}

variable "budget_email" {
  description = "PERSONAL email that receives the budget alerts."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_email))
    error_message = "The budget_email must be a valid email address."
  }
}

variable "budget_limit_usd" {
  description = "Monthly budget for the WHOLE account. If the account already has spend, use your usual spend + 5."
  type        = number
  default     = 5
}

variable "infra_state_key" {
  description = "S3 key of the infra/ state. Must match the key in infra/backend.tf."
  type        = string
  default     = "infra/terraform.tfstate"
}
