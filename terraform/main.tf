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
resource "aws_secretsmanager_secret_version" "google_credentials" {
  secret_id     = aws_secretsmanager_secret.google_credentials.id
  secret_string = jsonencode({
    type                        = "service_account"
    project_id                  = "celtic-facility-465313-e4"
    private_key_id              = "25137bacf5d92b3ec60a3d7db549c051c2eb5405"
    private_key                 = "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDEJrLgYw0WnEx1\nokRTx1ZmNmV+oHppcOABmmRc5W8nnJltxE2A/zoWS6WEiQ2jTAkEpxT2ET7enVPI\nyBF9CMgVWQRJDQhclVp47OqtfOT0Ujt3ie0eW8RbrGlxjxBuhF2gVZbE42zCrGv+\nfReJTjRvnQS7lmFotswHvqAQep8elaJMN4qpux+b3djPjeDypHI9mTu8Wiz/AY12\n8G7ptj3SueBEqaqZtoWquZZq6Dc4Gf+Q+UDgSf+MCvq2NfIjy4QyogItwFKoc2Jj\n9R+wTjhVmoyi0mKHIyrBOAFNw6Dot+MDfbQ9s99C9qr3n5yrY5dlWDY/ubJPmSNv\neJT1C3hFAgMBAAECggEAJDldWXERbraIrES+R5aNjyzGi58JXEWbKNChbkJ0x6T0\n9L+G7Ka1zH5F3/cLjLezBqfwiAzhRm1Zlr/T8vpXMRISZ4c/nxF59tER+d4RzkkN\ncGMJZkzeM2vgwTcBetd5Du4ffNbfNAhxnTruyM2ng2FFCXuZG6R+g4OhvclXb2cx\n5JRGxodX9tBHOZh6Z3ZBtpJKVnzvihKYVEF1KFgpsovAac8rLYovb5Rh5ruWWZmu\ngIptKSfIFZ8YXNH0EtrqebKRcANZb3WpUGl0rNR7CaLPkvL1hRjNUdorYVg9nzg1\nkNUVySB3kU2mhun2fIQGFruUhaypfM8elDxh3xLc1QKBgQDxkZQ2BJ8zfICdLnSc\nXoKgdNpQIN3lQoYFNDuPv1U+L8I/TD7f6u62CJP/DYs5vcjIzl/D7JNpkhKpl5Lq\nLsq4iAh8uapE957UibsTjEwaM42qiARQonn2yne5UakL3SM/b6RuCGvEk/Tk5faF\nW0iZ05Wgz9l3I4U4taX8oD9SOwKBgQDP3odsh4lPFp+V0rogjvUEK9zqXTV2ppZt\nyB2Fol29hbRzm+3kB1tCuaZ65Ff0S0D9AtbK0g/cyLmPVC+8JzJODd00QrjvESdI\nlC1Kgt7nHWEFQ5hwsb3m2g8Weo6kii13EsRMvVMWpgNHcUcAdXhHOZtB1vyn3HiH\nF+1/cnU3fwKBgEdS6mXAm5jCC99c1gVNSlhB6Ct8aMfGCngC4gshPPPtefbidjX6\n0ZxhkADgaNkVlfDkLhZVBXlILcZxAGmwgx5U29ynnQRb8ENknx24cMfTrOJK4qtE\nLaqWQR8wYy8jjcKvHed3CQqzfL0QwObC+v6gIC+o7tZkYHNL/sRGNCv9AoGAGXJ9\nk6y4A4WafcXxYUD+/8a64boNbHwSWFgyPQTWgvgWUjzZj5vS8UU2+z5vAgogZ5js\nYKH8rSOpi8FboqYNw35xAQ/WAfZQn9L8BG4nCZYQJYvT4p/vxo4VYMQaKEx+KmCS\nxW47+L7UEe/tKEI5Okb0GchO3+Heo3MrcPm7HdMCgYA6ATnv41qEan5JbjGNt1X6\ncdoSqC7a88MkGOvjJxLRvkmaTyq8OZAI6DJSYE4czhmLTkHvSEKgo8GMiwBfcTWs\n9LKZy6n7hbZdmGvEsokRAJj0XGG87TVy9E4Iov6PGEgTk5h8vC3uqwLnvfxjtpMO\n7YtSm89xD8Uz85meGooUFw==\n-----END PRIVATE KEY-----\n"
    client_email                = "gdrive-backup-acc@celtic-facility-465313-e4.iam.gserviceaccount.com"
    client_id                   = "108382266205555175998"
    auth_uri                    = "https://accounts.google.com/o/oauth2/auth"
    token_uri                   = "https://oauth2.googleapis.com/token"
    auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
    client_x509_cert_url        = "https://www.googleapis.com/robot/v1/metadata/x509/gdrive-backup-acc%40celtic-facility-465313-e4.iam.gserviceaccount.com"
    universe_domain             = "googleapis.com"
  })

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