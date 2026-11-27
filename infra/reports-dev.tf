# =============================================================================
# reports (dev): internal service that exports operational reports (CSV)
# for the operations team. Development environment.
# =============================================================================

locals {
  reports_dev_name               = "reports-dev"
  reports_dev_environment        = "development"
  reports_dev_env_short          = "dev"
  reports_dev_log_retention_days = 14

  reports_dev_tags = {
    Environment = local.reports_dev_environment
    App         = "reports"
  }
}

# ------------------------------------------------------------- S3 (exports)

resource "aws_s3_bucket" "reports_dev_exports" {
  bucket = "acme-${local.reports_dev_name}-exports-${local.name_suffix}"

  tags = merge(local.reports_dev_tags, {
    Name = "${local.reports_dev_name}-exports"
    Data = "reports"
  })
}

resource "aws_s3_bucket_public_access_block" "reports_dev_exports" {
  bucket = aws_s3_bucket.reports_dev_exports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports_dev_exports" {
  bucket = aws_s3_bucket.reports_dev_exports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "reports_dev_exports" {
  bucket = aws_s3_bucket.reports_dev_exports.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# ------------------------------------------------------------- Security group

resource "aws_security_group" "reports_dev_app" {
  name        = "acme-${local.reports_dev_name}-app"
  description = "reports (dev) application tasks"
  vpc_id      = aws_vpc.env[local.reports_dev_env_short].id

  tags = merge(local.reports_dev_tags, { Name = "${local.reports_dev_name}-app" })
}

resource "aws_vpc_security_group_ingress_rule" "reports_dev_https" {
  security_group_id = aws_security_group.reports_dev_app.id
  description       = "HTTPS from inside the dev VPC"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = aws_vpc.env[local.reports_dev_env_short].cidr_block
}

resource "aws_vpc_security_group_egress_rule" "reports_dev_all" {
  security_group_id = aws_security_group.reports_dev_app.id
  description       = "All outbound traffic"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------- IAM (task role)

resource "aws_iam_role" "reports_dev_task" {
  name               = "acme-${local.reports_dev_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = local.reports_dev_tags
}

# Least privilege: reports can list its bucket and read/write its exports.
data "aws_iam_policy_document" "reports_dev_task" {
  statement {
    sid       = "ListOwnBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.reports_dev_exports.arn]
  }

  statement {
    sid       = "ReadWriteOwnExports"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.reports_dev_exports.arn}/*"]
  }
}

resource "aws_iam_role_policy" "reports_dev_task" {
  name   = "bucket-access"
  role   = aws_iam_role.reports_dev_task.id
  policy = data.aws_iam_policy_document.reports_dev_task.json
}

# ------------------------------------------------------------- Logs

resource "aws_cloudwatch_log_group" "reports_dev" {
  name              = "/acme/${local.reports_dev_name}"
  retention_in_days = local.reports_dev_log_retention_days
  tags              = local.reports_dev_tags
}
