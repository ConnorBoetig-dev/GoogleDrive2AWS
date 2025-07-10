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
- **Deployment Method**: AWS Console (GUI) preferred

## Lambda Environment Variables
- `S3_BUCKET` - S3 bucket name
- `SECRET_NAME` - Secrets Manager secret name

## What I Need
Clear documentation and scripts to manually provision this exact setup in a new AWS account. Just the baseline - I'll add features later.

## Project Structure
```
GoogleDrive2AWS/
├── lambda/
│   ├── google-drive-backup/
│   │   ├── gdrive.py           # Main Lambda code
│   │   └── ENTERPRISE_SETUP.md # Enterprise setup guide
│   └── gmail-backup/
│       └── lambda_function.py  # Gmail backup code
├── docs/
│   ├── CONTEXT.md             # This file
│   ├── improvements.md        # Enhancement proposals
│   └── SECRET_HANDLING.md     # Security guidelines
├── ARCHITECTURE.md            # System design
├── REPLICATION.md            # Manual setup guide
├── RESTORATION_DESIGN.md     # Restore procedures
└── README.md                 # Project overview
```

## Lambda Code Summary
- Backs up all files accessible by the service account
- Supports both personal drives and Shared Drives
- Downloads files and converts Google Docs→PDF, Sheets→Excel
- Uploads to S3 at path: {username}/{date}/{folder_path}/{filename}
- Uses KMS encryption for S3 uploads
- Supports incremental backups with DynamoDB state tracking
- Concurrent processing with configurable thread count

## Important Notes
- Everything is already working in AWS
- Manual setup instructions are provided in REPLICATION.md
- Keep it simple - no fancy features yet
- AWS Console (GUI) steps are documented throughout
- Can be deployed using AWS Console, CLI, or SDKs (Console preferred)
