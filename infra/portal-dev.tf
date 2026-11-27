# =============================================================================
# portal (dev): patient-facing web portal, development environment.
# One file per app/env: to add an app or environment, copy this file and
# change the locals block plus the resource name prefixes.
# =============================================================================

locals {
  portal_dev_name               = "portal-dev"
  portal_dev_environment        = "development"
  portal_dev_env_short          = "dev"
  portal_dev_log_retention_days = 14

  portal_dev_tags = {
    Environment = local.portal_dev_environment
    App         = "portal"
  }
}

# ------------------------------------------------------------- S3 (documents)

resource "aws_s3_bucket" "portal_dev_data" {
  bucket = "acme-${local.portal_dev_name}-data-${local.name_suffix}"

  tags = merge(local.portal_dev_tags, {
    Name       = "${local.portal_dev_name}-data"
    Data       = "documents"
    CostCenter = "patient-experience"
  })
}

resource "aws_s3_bucket_public_access_block" "portal_dev_data" {
  bucket = aws_s3_bucket.portal_dev_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "portal_dev_data" {
  bucket = aws_s3_bucket.portal_dev_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "portal_dev_data" {
  bucket = aws_s3_bucket.portal_dev_data.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# ------------------------------------------------------------- Security group

resource "aws_security_group" "portal_dev_app" {
  name        = "acme-${local.portal_dev_name}-app"
  description = "portal (dev) application tasks"
  vpc_id      = aws_vpc.env[local.portal_dev_env_short].id

  tags = merge(local.portal_dev_tags, { Name = "${local.portal_dev_name}-app" })
}

# aws_vpc_security_group_ingress_rule: one resource per rule (instead of inline
# rules), so adding or removing a rule never rewrites the whole security group.
resource "aws_vpc_security_group_ingress_rule" "portal_dev_https" {
  security_group_id = aws_security_group.portal_dev_app.id
  description       = "HTTPS from inside the dev VPC"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = aws_vpc.env[local.portal_dev_env_short].cidr_block
}

resource "aws_vpc_security_group_egress_rule" "portal_dev_all" {
  security_group_id = aws_security_group.portal_dev_app.id
  description       = "All outbound traffic"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------- IAM (task role)

resource "aws_iam_role" "portal_dev_task" {
  name               = "acme-${local.portal_dev_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = local.portal_dev_tags
}

# Least privilege: the portal can only list its bucket and read/write its objects.
data "aws_iam_policy_document" "portal_dev_task" {
  statement {
    sid       = "ListOwnBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.portal_dev_data.arn]
  }

  statement {
    sid       = "ReadWriteOwnObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.portal_dev_data.arn}/*"]
  }
}

resource "aws_iam_role_policy" "portal_dev_task" {
  name   = "bucket-access"
  role   = aws_iam_role.portal_dev_task.id
  policy = data.aws_iam_policy_document.portal_dev_task.json
}

# ------------------------------------------------------------- Logs

resource "aws_cloudwatch_log_group" "portal_dev" {
  name              = "/acme/${local.portal_dev_name}"
  retention_in_days = local.portal_dev_log_retention_days
  tags              = local.portal_dev_tags
}
