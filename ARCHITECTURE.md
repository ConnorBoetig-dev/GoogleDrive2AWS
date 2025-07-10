# Google Drive Enterprise Backup System - Architecture Overview

## System Architecture

This solution creates an automated, serverless backup system that periodically copies files from Google Drive (including Shared Drives) to Amazon S3, with incremental backup capabilities and enterprise-grade performance. The system can be deployed manually using AWS CLI/Console or programmatically via AWS SDKs.

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

**S3 Bucket Setup via AWS Console:**
- Navigate to **S3** → **Create bucket**
- Bucket name: `gdrive-backup-{unique-id}`
- In bucket settings:
  - **Versioning**: Enable
  - **Default encryption**: Enable server-side encryption (SSE-S3 or SSE-KMS)
  - **Block Public Access**: Keep all settings enabled
- After creation, go to **Management** tab → **Create lifecycle rule** for cost optimization

**DynamoDB Table Setup via AWS Console:**
- Navigate to **DynamoDB** → **Create table**
- Table name: `gdrive-backup-state`
- Partition key: `file_id` (String)
- Table settings: Customize settings → On-demand mode
- After creation: **Additional settings** → **Time to Live** → Enable on `ttl` attribute

**Secrets Manager Setup via AWS Console:**
- Navigate to **Secrets Manager** → **Store a new secret**
- Secret type: "Other type of secret"
- In "Plaintext" tab: Paste entire Google service account JSON
- Secret name: `connor-gdrive-backup-credentials` (or your chosen name)

**Lambda Function Setup via AWS Console:**
- Navigate to **Lambda** → **Create function**
- Function name: `gdrive-backup`
- Runtime: Python 3.9+
- Architecture: x86_64
- After creation, configure:
  - **Configuration** → **General configuration**: Memory 2048 MB, Timeout 900 seconds
  - **Runtime settings**: Handler `gdrive.lambda_handler`

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

**Lambda Execution Role Setup via AWS Console:**
- Navigate to **IAM** → **Roles** → **Create role**
- Trusted entity: AWS service → Lambda
- Attach `AWSLambdaBasicExecutionRole`
- After creation, add inline policy with permissions for:
  - **DynamoDB**: GetItem, PutItem, UpdateItem on the state table
  - **S3**: PutObject, GetObject, ListBucket, multipart operations on your bucket
  - **Secrets Manager**: GetSecretValue on your secret
  - **CloudWatch**: PutMetricData
  - **KMS**: Decrypt, GenerateDataKey (if using KMS encryption)

**EventBridge Rule Setup via AWS Console:**
- Navigate to **EventBridge** → **Rules** → **Create rule**
- Rule type: Schedule
- Schedule pattern: Cron expression `0 16 */2 * ? *` (Every other day at 4 PM)
- Target: Lambda function → Select your `gdrive-backup` function

### 3. Code Deployment

**Code Deployment via AWS Console:**

1. **Create Lambda Layer for Dependencies:**
   - Prepare dependencies locally:
     ```bash
     pip install --target ./python google-api-python-client google-auth google-auth-httplib2
     zip -r layer.zip python/
     ```
   - Navigate to **Lambda** → **Layers** → **Create layer**
   - Upload the `layer.zip` file
   - Compatible runtimes: Python 3.9

2. **Deploy Function Code:**
   - Create ZIP file containing `gdrive.py`
   - Navigate to **Lambda** → Select your function
   - **Code** tab → **Upload from** → **.zip file**
   - Upload your function ZIP

3. **Attach Layer:**
   - In function configuration, scroll to **Layers**
   - Click **Add a layer** → **Custom layers**
   - Select your dependencies layer

4. **Configure Environment Variables:**
   - **Configuration** → **Environment variables** → **Edit**
   - Add all required variables (S3_BUCKET, SECRET_NAME, etc.)

For detailed step-by-step instructions, see [REPLICATION.md](REPLICATION.md).

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