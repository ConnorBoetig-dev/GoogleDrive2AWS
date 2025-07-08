# AWS Backup System - Context for Claude Code

## What I Have Working in AWS
- Lambda function that backs up Google Drive to S3 (tested and working)
- Lambda layer with Google Drive API dependencies
- S3 bucket with lifecycle policies (30d→IA, 90d→Glacier, 365d→Deep Archive, 7yr expiration)
- Secrets Manager with Google service account credentials
- IAM role for Lambda execution
- No scheduling yet - I trigger it manually

## Current Setup
- **OS**: Debian
- **Project Directory**: ~/AWS-BACKUPS2/
- **Lambda Handler**: GDRIVE-backup.lambda_handler
- **Runtime**: Python 3.9
- **Memory**: 512 MB
- **Timeout**: 300 seconds

## Lambda Environment Variables
- `S3_BUCKET` - S3 bucket name
- `SECRET_NAME` - Secrets Manager secret name

## What I Need
Simple Terraform configuration to auto-provision this exact setup in a new AWS account. Just the baseline - I'll add features later.

## Project Structure
```
AWS-BACKUPS2/
├── lambda/
│   └── google-drive-backup/
│       └── GDRIVE-backup.py    # My working Lambda code
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars
└── CLAUDE_CODE_CONTEXT.md      # This file
```

## Lambda Code Summary
- Searches for "backup test" folder in Google Drive
- Downloads files and converts Google Docs→PDF, Sheets→Excel
- Uploads to S3 at path: gdrive-backup/YYYY-MM-DD/filename
- Uses KMS encryption for S3 uploads

## Important Notes
- Everything is already working in AWS
- I just need Terraform to recreate it elsewhere
- Keep it simple - no fancy features yet
- I'll handle packaging/deployment myself
