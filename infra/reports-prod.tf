# =============================================================================
# reports (prod): internal service that exports operational reports (CSV)
# for the operations team. Production environment.
# =============================================================================

locals {
  reports_prod_name               = "reports-prod"
  reports_prod_environment        = "production"
  reports_prod_env_short          = "prod"
  reports_prod_log_retention_days = 90

  reports_prod_tags = {
    Environment = local.reports_prod_environment
    App         = "reports"
  }
}

# ------------------------------------------------------------- S3 (exports)

resource "aws_s3_bucket" "reports_prod_exports" {
  bucket = "acme-${local.reports_prod_name}-exports-${local.name_suffix}"

  tags = merge(local.reports_prod_tags, {
    Name = "${local.reports_prod_name}-exports"
    Data = "reports"
  })
}

resource "aws_s3_bucket_public_access_block" "reports_prod_exports" {
  bucket = aws_s3_bucket.reports_prod_exports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports_prod_exports" {
  bucket = aws_s3_bucket.reports_prod_exports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "reports_prod_exports" {
  bucket = aws_s3_bucket.reports_prod_exports.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Production: deleted or overwritten exports can be recovered.
resource "aws_s3_bucket_versioning" "reports_prod_exports" {
  bucket = aws_s3_bucket.reports_prod_exports.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ------------------------------------------------------------- Security group

resource "aws_security_group" "reports_prod_app" {
  name        = "acme-${local.reports_prod_name}-app"
  description = "reports (prod) application tasks"
  vpc_id      = aws_vpc.env[local.reports_prod_env_short].id

  tags = merge(local.reports_prod_tags, { Name = "${local.reports_prod_name}-app" })
}

resource "aws_vpc_security_group_ingress_rule" "reports_prod_https" {
  security_group_id = aws_security_group.reports_prod_app.id
  description       = "HTTPS from inside the prod VPC"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = aws_vpc.env[local.reports_prod_env_short].cidr_block
}

resource "aws_vpc_security_group_egress_rule" "reports_prod_all" {
  security_group_id = aws_security_group.reports_prod_app.id
  description       = "All outbound traffic"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------- IAM (task role)

resource "aws_iam_role" "reports_prod_task" {
  name               = "acme-${local.reports_prod_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = local.reports_prod_tags
}

data "aws_iam_policy_document" "reports_prod_task" {
  statement {
    sid       = "ListOwnBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.reports_prod_exports.arn]
  }

  statement {
    sid       = "ReadWriteOwnExports"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.reports_prod_exports.arn}/*"]
  }
}

resource "aws_iam_role_policy" "reports_prod_task" {
  name   = "bucket-access"
  role   = aws_iam_role.reports_prod_task.id
  policy = data.aws_iam_policy_document.reports_prod_task.json
}

# ------------------------------------------------------------- Logs

resource "aws_cloudwatch_log_group" "reports_prod" {
  name              = "/acme/${local.reports_prod_name}"
  retention_in_days = local.reports_prod_log_retention_days
  tags              = local.reports_prod_tags
}
