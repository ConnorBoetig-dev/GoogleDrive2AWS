terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Random suffix for unique naming
resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

# S3 Bucket for backups
resource "aws_s3_bucket" "backup_bucket" {
  bucket = "${var.project_name}-${random_string.suffix.result}"

  tags = {
    Name        = "${var.project_name}-backup-bucket"
    Environment = var.environment
  }
}

# S3 Bucket Versioning
resource "aws_s3_bucket_versioning" "backup_bucket_versioning" {
  bucket = aws_s3_bucket.backup_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 Bucket Encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "backup_bucket_encryption" {
  bucket = aws_s3_bucket.backup_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

# S3 Bucket Public Access Block
resource "aws_s3_bucket_public_access_block" "backup_bucket_pab" {
  bucket = aws_s3_bucket.backup_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# S3 Bucket Lifecycle Configuration
resource "aws_s3_bucket_lifecycle_configuration" "backup_bucket_lifecycle" {
  bucket = aws_s3_bucket.backup_bucket.id

  rule {
    id     = "backup-lifecycle"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    transition {
      days          = 365
      storage_class = "DEEP_ARCHIVE"
    }

    expiration {
      days = 2555  # 7 years
    }
  }
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-lambda-logs"
    Environment = var.environment
  }
}

# Secrets Manager Secret
resource "aws_secretsmanager_secret" "google_credentials" {
  name                    = "${var.project_name}-google-credentials-${random_string.suffix.result}"
  description             = "Google Service Account credentials for Drive API access"
  recovery_window_in_days = var.secret_recovery_window

  tags = {
    Name        = "${var.project_name}-google-credentials"
    Environment = var.environment
  }
}

# Secrets Manager Secret Version
# This will be populated from a file or environment variable
resource "aws_secretsmanager_secret_version" "google_credentials" {
  secret_id     = aws_secretsmanager_secret.google_credentials.id
  secret_string = var.google_credentials_json

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = {
    Name        = "${var.project_name}-lambda-role"
    Environment = var.environment
  }
}

# IAM Policy for Lambda
resource "aws_iam_policy" "lambda_policy" {
  name        = "${var.project_name}-lambda-policy"
  description = "Policy for Google Drive backup Lambda function"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.backup_bucket.arn,
          "${aws_s3_bucket.backup_bucket.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "s3.${var.aws_region}.amazonaws.com"
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.google_credentials.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:*"
      }
    ]
  })
}

# Attach policy to role
resource "aws_iam_role_policy_attachment" "lambda_policy_attachment" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

# Lambda Layer for Google Drive dependencies
resource "aws_lambda_layer_version" "google_drive_layer" {
  filename                 = var.lambda_layer_path
  layer_name               = "${var.project_name}-google-drive-dependencies"
  compatible_runtimes      = ["python3.9"]
  compatible_architectures = ["x86_64"]

  lifecycle {
    ignore_changes = [filename]
  }
}

# Lambda Function
resource "aws_lambda_function" "backup_function" {
  filename         = var.lambda_function_path
  function_name    = var.lambda_function_name
  role            = aws_iam_role.lambda_role.arn
  handler         = "GDRIVE-backup.lambda_handler"
  source_code_hash = var.lambda_function_path != "" ? filebase64sha256(var.lambda_function_path) : null
  runtime         = "python3.9"
  memory_size     = 512
  timeout         = 300

  environment {
    variables = {
      S3_BUCKET    = aws_s3_bucket.backup_bucket.id
      SECRET_NAME  = aws_secretsmanager_secret.google_credentials.name
      MAX_WORKERS  = "5"
    }
  }

  layers = [aws_lambda_layer_version.google_drive_layer.arn]

  depends_on = [
    aws_iam_role_policy_attachment.lambda_policy_attachment,
    aws_cloudwatch_log_group.lambda_log_group,
  ]

  tags = {
    Name        = "${var.project_name}-backup-function"
    Environment = var.environment
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }
}