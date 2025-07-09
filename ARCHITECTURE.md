# Google Drive Enterprise Backup System - Architecture Overview

## System Architecture

This solution creates an automated, serverless backup system that periodically copies files from Google Drive (including Shared Drives) to Amazon S3, with incremental backup capabilities and enterprise-grade performance.

### Core Components

1. **Google Service Account** - Authenticates with Google Drive API
2. **AWS Lambda Function** - Executes the backup logic
3. **Amazon S3 Bucket** - Stores the backed-up files
4. **AWS Secrets Manager** - Securely stores Google credentials
5. **Amazon DynamoDB** - Tracks file state for incremental backups
6. **Amazon EventBridge** - Schedules automatic backups
7. **Amazon CloudWatch** - Logs and metrics

## Setup Process

### 1. Google Cloud Setup

**Create Service Account:**
- Create a new Google Cloud Project
- Enable Google Drive API
- Create a Service Account with "Viewer" role
- Generate and download JSON key file
- Share Google Drive files/folders with the service account email
- For Shared Drives: Add service account as member with "Viewer" access

### 2. AWS Infrastructure

**S3 Bucket:**
- Create bucket (e.g., `gdrive-backup-{unique-id}`)
- Enable versioning
- Enable server-side encryption (AWS KMS)
- Configure lifecycle policies for cost optimization (optional)

**DynamoDB Table:**
- Table name: `gdrive-backup-state`
- Partition key: `file_id` (String)
- Billing mode: On-demand
- Enable TTL on `ttl` attribute (30-day expiration)

**Secrets Manager:**
- Create secret named `connor-gdrive-backup-credentials` (or your chosen name)
- Store the entire Google service account JSON as the secret value

**Lambda Function:**
- Runtime: Python 3.9+
- Memory: 2048 MB (minimum 1024 MB)
- Timeout: 900 seconds (15 minutes)
- Handler: `gdrive.lambda_handler`
- Architecture: x86_64

**Environment Variables:**
```
S3_BUCKET=gdrive-backup-{unique-id}
SECRET_NAME=connor-gdrive-backup-credentials
DYNAMODB_TABLE=gdrive-backup-state
MAX_WORKERS=3
BATCH_SIZE=50
ENABLE_SHARED_DRIVES=true
RATE_LIMIT_DELAY=0.05
LARGE_FILE_THRESHOLD=104857600
```

**Lambda Execution Role:**
Create IAM role with trust relationship to Lambda service and attach policy with:
- DynamoDB: GetItem, PutItem, UpdateItem on the state table
- S3: PutObject, GetObject, ListBucket, multipart operations on your bucket
- Secrets Manager: GetSecretValue on your secret
- CloudWatch: PutMetricData, CreateLogGroup, CreateLogStream, PutLogEvents
- KMS: Decrypt, GenerateDataKey (for encryption)

**EventBridge Rule:**
- Schedule expression: `cron(0 16 */2 * ? *)` (Every other day at 4 PM)
- Target: Your Lambda function

### 3. Code Deployment

Deploy the Python code (`gdrive.py`) to Lambda with required dependencies:
- google-auth
- google-auth-httplib2
- google-api-python-client
- boto3 (included in Lambda runtime)

## How It Works

### Execution Flow

1. **EventBridge triggers Lambda** on schedule
2. **Lambda retrieves credentials** from Secrets Manager (cached after first call)
3. **Creates Google Drive service** using service account
4. **Lists all accessible files** from:
   - Files shared directly with service account
   - Shared Drives where service account is a member
5. **For each file:**
   - Downloads file content and calculates SHA256 hash
   - Checks DynamoDB for previous backup state
   - Skips if file unchanged (same hash)
   - Uploads changed/new files to S3
   - Updates DynamoDB with new state
6. **Publishes metrics** to CloudWatch

### Key Features

**Incremental Backups:**
- Only changed files are backed up after initial run
- Uses SHA256 hashing to detect changes
- DynamoDB tracks: file_id, hash, modified_time, s3_key

**Folder Structure Preservation:**
- Maintains Google Drive folder hierarchy in S3
- Path format: `{username}/{date}/{folder_path}/{filename}`
- Shared Drives: `{username}/shared-drives/{drive_name}/{date}/{path}`

**Performance Optimizations:**
- Concurrent processing (3 threads default)
- Streaming for large files
- Multipart upload for files >100MB
- Batch processing to reduce API calls

**Error Handling:**
- Thread-safe Google Drive service creation
- Retry logic for downloads and uploads
- Continues processing even if individual files fail
- Detailed CloudWatch logging

### Monitoring

**CloudWatch Metrics:**
- FilesProcessed - Total files examined
- FilesSuccess - Successfully backed up
- BytesBackedUp - Total data transferred
- Dimensions by UserEmail and DriveName

**CloudWatch Logs:**
- Detailed execution logs
- Error tracking
- Performance metrics

## Cost Considerations

- **Lambda:** Pay per invocation and compute time
- **S3:** Storage + requests + data transfer
- **DynamoDB:** On-demand pricing for read/write
- **Secrets Manager:** ~$0.40/month per secret
- **Data Transfer:** Ingress from Google is free, egress charges apply

## Security

- Google credentials never exposed in code
- All data encrypted in transit and at rest
- IAM least-privilege access
- S3 bucket encryption with KMS
- No public access to backup data

This architecture provides a robust, scalable, and cost-effective solution for backing up Google Drive data to AWS, suitable for both personal and enterprise use cases.