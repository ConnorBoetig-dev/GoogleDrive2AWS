# Google Drive to AWS S3 Backup System

## Overview
This system backs up Google Drive files shared with a service account to AWS S3, with support for multiple users.

## Features
- Backs up all files shared with the service account
- Organizes backups by user email and date
- Supports Google Workspace file conversion (Docs→PDF, Sheets→Excel, etc.)
- Deduplication using SHA256 hashing
- Concurrent processing for better performance
- CloudWatch metrics per user
- S3 lifecycle policies for cost optimization

## File Structure in S3
```
gdrive-backup/
├── user1@example.com/
│   ├── 2024-01-10/
│   │   ├── Documents/
│   │   │   ├── report.pdf
│   │   │   └── budget.xlsx
│   │   └── Projects/
│   │       └── presentation.pptx
│   └── 2024-01-11/
│       └── ...
└── user2@example.com/
    └── 2024-01-10/
        └── ...
```

## Setup Instructions

1. **Deploy AWS Infrastructure**
   - Follow the comprehensive [REPLICATION.md](REPLICATION.md) guide for AWS Console setup
   - Create required resources via AWS Console:
     - Navigate to **S3** → Create bucket with versioning and lifecycle policies
     - Navigate to **Lambda** → Create function with appropriate IAM role
     - Navigate to **Secrets Manager** → Store Google credentials
     - (Optional) Navigate to **DynamoDB** → Create table for incremental backups

2. **Configure Google Service Account**
   - Create a Google Cloud service account
   - Enable Google Drive API
   - Download JSON credentials
   - Store credentials in AWS Secrets Manager

3. **Share files with the service account**
   - Users share their Google Drive files/folders with the service account email
   - Grant "Viewer" permission for read-only access

4. **Deploy Lambda Function**
   - Package Lambda function locally:
     ```bash
     cd lambda/google-drive-backup/
     zip -r ../../google-drive-backup.zip gdrive.py
     ```
   - Navigate to **Lambda** → Select your function → **Code** tab
   - Click **Upload from** → **.zip file**
   - Select the `google-drive-backup.zip` file
   - Click **Save**

## Lambda Function

- **gdrive.py**: Main backup function with:
  - Support for personal and shared drives
  - User-based organization in S3
  - Concurrent processing with threading
  - Deduplication using SHA256 hashing
  - CloudWatch metrics per user
  - Comprehensive error handling
  - Google Workspace file conversion (Docs→PDF, Sheets→Excel, etc.)
  - Rate limiting protection
  - Multipart upload for large files

## Environment Variables
- `S3_BUCKET`: Target S3 bucket for backups
- `SECRET_NAME`: AWS Secrets Manager secret containing Google credentials
- `MAX_WORKERS`: Number of concurrent file processors (default: 5)
- `ENABLE_SHARED_DRIVES`: Enable/disable Shared Drive backup (true/false)
- `RATE_LIMIT_DELAY`: Delay between API calls in seconds (default: 0.05)
- `LARGE_FILE_THRESHOLD`: Threshold for multipart upload in bytes (default: 104857600)
- `DYNAMODB_TABLE`: (Optional) DynamoDB table name for incremental backups

## Monitoring
Check CloudWatch Metrics under the "GDriveBackup" namespace for:
- Files processed per user
- Success/failure rates
- Bytes backed up

## See Also
- [REPLICATION.md](REPLICATION.md) - Complete manual setup guide without Terraform
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture and design
- [Improvement Suggestions](docs/improvements.md) - Detailed enhancement proposals
- [Context](docs/CONTEXT.md) - Original project context
- [Secret Handling](docs/SECRET_HANDLING.md) - Security best practices
- [Enterprise Setup](lambda/google-drive-backup/ENTERPRISE_SETUP.md) - Enterprise deployment guide
- [Restoration Design](RESTORATION_DESIGN.md) - Backup restoration procedures