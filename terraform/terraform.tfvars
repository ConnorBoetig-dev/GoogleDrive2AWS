# AWS Configuration
aws_region = "us-east-1"

# Project Configuration
project_name = "gdrive-backup"
environment  = "production"

# Lambda Configuration
lambda_function_name = "google-drive-backup"
lambda_function_path = "../lambda/google-drive-backup.zip"  # Path to your Lambda deployment package
lambda_layer_path    = "../lambda/google-drive-layer.zip"   # Path to your Lambda layer package

# CloudWatch Configuration
log_retention_days = 30

# Secrets Manager Configuration
secret_recovery_window = 7