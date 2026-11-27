# =============================================================================
# Values shared by every app/env file.
# =============================================================================

data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"] # regular AZs only, no Local Zones
  }
}

# Bucket names are global. A random suffix keeps them unique without putting
# the account ID in names that show up in public CI logs.
resource "random_id" "suffix" {
  byte_length = 3
}

locals {
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
  name_suffix = random_id.suffix.hex
}

# Trust policy shared by every app's task role: "ECS tasks may assume this role".
data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}
