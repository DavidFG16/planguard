# =============================================================================
# portal (prod): patient-facing web portal, production environment.
# Same shape as portal-dev.tf, plus bucket versioning and longer log retention.
# =============================================================================

locals {
  portal_prod_name               = "portal-prod"
  portal_prod_environment        = "production"
  portal_prod_env_short          = "prod"
  portal_prod_log_retention_days = 90

  portal_prod_tags = {
    Environment = local.portal_prod_environment
    App         = "portal"
  }
}

# ------------------------------------------------------------- S3 (documents)

resource "aws_s3_bucket" "portal_prod_data" {
  bucket = "acme-${local.portal_prod_name}-data-${local.name_suffix}"

  tags = merge(local.portal_prod_tags, {
    Name = "${local.portal_prod_name}-data"
    Data = "documents"
  })
}

resource "aws_s3_bucket_public_access_block" "portal_prod_data" {
  bucket = aws_s3_bucket.portal_prod_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "portal_prod_data" {
  bucket = aws_s3_bucket.portal_prod_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "portal_prod_data" {
  bucket = aws_s3_bucket.portal_prod_data.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Production: deleted or overwritten documents can be recovered.
resource "aws_s3_bucket_versioning" "portal_prod_data" {
  bucket = aws_s3_bucket.portal_prod_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ------------------------------------------------------------- Security group

resource "aws_security_group" "portal_prod_app" {
  name        = "acme-${local.portal_prod_name}-app"
  description = "portal (prod) application tasks"
  vpc_id      = aws_vpc.env[local.portal_prod_env_short].id

  tags = merge(local.portal_prod_tags, { Name = "${local.portal_prod_name}-app" })
}

resource "aws_vpc_security_group_ingress_rule" "portal_prod_https" {
  security_group_id = aws_security_group.portal_prod_app.id
  description       = "HTTPS from inside the prod VPC"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = aws_vpc.env[local.portal_prod_env_short].cidr_block
}

# Temporary: SSH into the portal tasks to debug the login timeouts.
resource "aws_vpc_security_group_ingress_rule" "portal_prod_ssh" {
  security_group_id = aws_security_group.portal_prod_app.id
  description       = "SSH for debugging"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "portal_prod_all" {
  security_group_id = aws_security_group.portal_prod_app.id
  description       = "All outbound traffic"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------- IAM (task role)

resource "aws_iam_role" "portal_prod_task" {
  name               = "acme-${local.portal_prod_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
  tags               = local.portal_prod_tags
}

data "aws_iam_policy_document" "portal_prod_task" {
  statement {
    sid       = "ListOwnBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.portal_prod_data.arn]
  }

  statement {
    sid       = "ReadWriteOwnObjects"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.portal_prod_data.arn}/*"]
  }
}

resource "aws_iam_role_policy" "portal_prod_task" {
  name   = "bucket-access"
  role   = aws_iam_role.portal_prod_task.id
  policy = data.aws_iam_policy_document.portal_prod_task.json
}

# ------------------------------------------------------------- Logs

resource "aws_cloudwatch_log_group" "portal_prod" {
  name              = "/acme/${local.portal_prod_name}"
  retention_in_days = local.portal_prod_log_retention_days
  tags              = local.portal_prod_tags
}
