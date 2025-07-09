# Google Drive Enterprise Backup - Setup Guide

## New Enterprise Features

### 1. **Incremental Backup Support**
- Only backs up files that have changed since last backup
- Uses DynamoDB to track file hashes and modification times
- Dramatically reduces storage costs and processing time

### 2. **Shared Drive Support**
- Fully supports Google Shared Drives (Team Drives)
- Organizes shared drive backups separately: `username/shared-drives/drive-name/`
- Enable/disable with `ENABLE_SHARED_DRIVES` environment variable

### 3. **Concurrent Processing**
- Processes multiple files in parallel (default: 5 workers)
- Configurable worker threads via `MAX_WORKERS` environment variable
- 5-10x performance improvement over sequential processing

### 4. **Large File Support**
- Streaming downloads to reduce memory usage
- Multipart uploads for files > 100MB
- Prevents Lambda memory errors with large files

### 5. **Improved Performance**
- Reduced rate limit delays (0.05s vs 0.1s)
- Batch processing support
- Optimized API calls with proper parameters

## Manual Setup Requirements

### 1. **DynamoDB Table**
Create a DynamoDB table with the following specifications:
```
Table Name: gdrive-backup-state
Partition Key: file_id (String)
Billing Mode: Pay per request (or provisioned with auto-scaling)
TTL Attribute: ttl (enabled on the 'ttl' field)
```

### 2. **Environment Variables**
Add these to your Lambda function:
```
S3_BUCKET=your-s3-bucket-name
SECRET_NAME=your-secret-name
DYNAMODB_TABLE=gdrive-backup-state
MAX_WORKERS=5                    # Number of concurrent threads (1-10)
BATCH_SIZE=50                    # Files per batch
ENABLE_SHARED_DRIVES=true        # Enable shared drive backup
RATE_LIMIT_DELAY=0.05           # Delay between operations (seconds)
LARGE_FILE_THRESHOLD=104857600   # 100MB in bytes
```

### 3. **Lambda Configuration**
- **Memory**: 1024 MB minimum (2048 MB recommended for large files)
- **Timeout**: 900 seconds (15 minutes)
- **Concurrency**: Set reserved concurrency to prevent throttling

### 4. **IAM Permissions**
Add these permissions to your Lambda execution role:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/gdrive-backup-state"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:PutObjectAcl",
                "s3:GetObject",
                "s3:CreateMultipartUpload",
                "s3:UploadPart",
                "s3:CompleteMultipartUpload"
            ],
            "Resource": "arn:aws:s3:::your-bucket-name/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "arn:aws:secretsmanager:*:*:secret:your-secret-name-*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricData"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "kms:Decrypt",
                "kms:GenerateDataKey"
            ],
            "Resource": "*"
        }
    ]
}
```

### 5. **Google Service Account Permissions**
For Shared Drives support, ensure your service account:
1. Is added as a member to each Shared Drive with "Viewer" access
2. Has domain-wide delegation enabled (if backing up entire domain)

## Usage Patterns

### First Run
The first run will backup ALL files and populate the DynamoDB state table. This will take longer and use more resources.

### Subsequent Runs
Only changed files will be backed up:
- New files
- Modified files (different hash)
- Files with newer modification times

### Monitoring
CloudWatch metrics are automatically published:
- `FilesProcessed` - Total files examined
- `FilesSuccess` - Successfully backed up files
- `BytesBackedUp` - Total data transferred

Metrics include dimensions for:
- `UserEmail` - For per-user tracking
- `DriveName` - For shared drive tracking

## Cost Optimization

1. **DynamoDB**: Uses TTL to automatically delete old entries after 30 days
2. **S3**: Enable lifecycle policies to move old backups to cheaper storage classes
3. **Lambda**: Reserved concurrency prevents unexpected scaling costs
4. **Incremental Backups**: Reduces data transfer and storage costs by 80-95%

## Troubleshooting

### Rate Limit Errors
- Reduce `MAX_WORKERS` to 3 or lower
- Increase `RATE_LIMIT_DELAY` to 0.1 or higher

### Memory Errors
- Increase Lambda memory to 3008 MB
- Reduce `BATCH_SIZE` to 25

### Timeout Errors
- Process specific users/drives separately
- Use Step Functions for orchestration of large backups

### Missing Shared Drives
- Verify service account has access to the shared drives
- Check `ENABLE_SHARED_DRIVES=true` is set
- Ensure proper API scopes are configured