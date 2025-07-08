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

1. **Deploy with Terraform**
   ```bash
   cd terraform/
   terraform init
   terraform plan
   terraform apply
   ```

2. **Share files with the service account**
   - Users share their Google Drive files/folders with: `gdrive-backup-acc@celtic-facility-465313-e4.iam.gserviceaccount.com`

3. **Package Lambda function** (if needed)
   ```bash
   cd lambda/google-drive-backup/
   zip -r ../../google-drive-backup.zip .
   ```

## Lambda Versions

- **GDRIVE-backup.py**: Original version (searches for "backup test" folder)
- **GDRIVE-backup-improved.py**: Enhanced version with:
  - User-based organization
  - Concurrent processing
  - Deduplication
  - CloudWatch metrics
  - Better error handling

## Environment Variables
- `S3_BUCKET`: Target S3 bucket for backups
- `SECRET_NAME`: AWS Secrets Manager secret containing Google credentials
- `MAX_WORKERS`: Number of concurrent file processors (default: 5)

## Monitoring
Check CloudWatch Metrics under the "GDriveBackup" namespace for:
- Files processed per user
- Success/failure rates
- Bytes backed up

## See Also
- [Improvement Suggestions](docs/improvements.md) - Detailed enhancement proposals
- [Context](docs/CONTEXT.md) - Original project context