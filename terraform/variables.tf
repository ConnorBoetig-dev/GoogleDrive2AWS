variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "gdrive-backup"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "lambda_function_name" {
  description = "Name of the Lambda function"
  type        = string
  default     = "google-drive-backup"
}

variable "lambda_function_path" {
  description = "Path to the Lambda function zip file"
  type        = string
  default     = ""
}

variable "lambda_layer_path" {
  description = "Path to the Lambda layer zip file"
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "secret_recovery_window" {
  description = "Number of days that AWS Secrets Manager waits before it can delete the secret"
  type        = number
  default     = 7
}

variable "google_credentials_json" {
  description = "Google service account credentials JSON string"
  type        = string
  sensitive   = true
}