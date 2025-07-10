# Google Drive to AWS S3 Backup - Manual Replication Guide

This guide explains how to manually replicate the Google Drive to AWS S3 backup solution in another AWS account without using Terraform.

## Overview

This system backs up Google Drive files (including Shared Drives) to AWS S3 using a Lambda function that connects to Google Drive API via a service account.

## Prerequisites

- AWS Account with appropriate permissions
- Google Cloud Platform account
- Access to Google Drive(s) you want to backup
- Python 3.9+ for local testing (optional)
- AWS CLI configured (optional but helpful)

## Step 1: Google Cloud Platform Setup

### 1.1 Create Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing one
3. Enable APIs:
   - Navigate to "APIs & Services" → "Library"
   - Search and enable: **Google Drive API**
   - (Optional) Enable **Gmail API** if backing up emails

4. Create Service Account:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "Service Account"
   - Name: `gdrive-backup-service-account`
   - Grant role: "Viewer" (or custom role with minimal permissions)
   - Click "Done"

5. Generate JSON Key:
   - Click on the created service account
   - Go to "Keys" tab → "Add Key" → "Create new key"
   - Choose JSON format
   - Save the downloaded file securely (you'll need this later)

### 1.2 Grant Google Drive Access

1. Copy the service account email (looks like: `service-account@project-id.iam.gserviceaccount.com`)
2. For each Google Drive/folder to backup:
   - Share with the service account email
   - Grant "Viewer" permission
3. For Shared Drives:
   - Add service account as member with "Content Manager" or "Viewer" role

## Step 2: AWS Infrastructure Setup

### 2.1 Create S3 Bucket

**AWS Console Steps:**

1. Navigate to **S3** → **Create bucket**
2. **Bucket configuration:**
   - Bucket name: `your-gdrive-backup-bucket`
   - AWS Region: `US East (N. Virginia) us-east-1` (or your preferred region)
   - Object Ownership: Keep default (ACLs disabled)
   
3. **Block Public Access settings:**
   - Check "Block all public access" (should be checked by default)
   - This ensures all four options are enabled:
     - Block public access to buckets and objects granted through new access control lists (ACLs)
     - Block public access to buckets and objects granted through any access control lists (ACLs)
     - Block public access to buckets and objects granted through new public bucket or access point policies
     - Block public access to buckets and objects granted through any public bucket or access point policies

4. **Bucket Versioning:**
   - Scroll to "Bucket Versioning" section
   - Select "Enable"
   
5. **Encryption:**
   - Under "Default encryption"
   - Enable "Server-side encryption"
   - Choose "Amazon S3 managed keys (SSE-S3)" or "AWS Key Management Service key (SSE-KMS)" for enhanced security
   
6. Click **Create bucket**

### 2.2 Create KMS Key (Optional but Recommended)

**AWS Console Steps:**

1. Navigate to **KMS** → **Customer managed keys** → **Create key**
2. **Configure key:**
   - Key type: "Symmetric"
   - Key usage: "Encrypt and decrypt"
   - Click **Next**
   
3. **Add labels:**
   - Alias: `alias/gdrive-backup-encryption`
   - Description: `GDrive Backup S3 Encryption Key`
   - Click **Next**
   
4. **Define key administrative permissions:**
   - Select your IAM user/role for administration
   - Click **Next**
   
5. **Define key usage permissions:**
   - Select the Lambda execution role (you'll create this later)
   - Or leave empty and update after creating the Lambda role
   - Click **Next**
   
6. Review and click **Finish**

### 2.3 Configure S3 Lifecycle Policy

**AWS Console Steps:**

1. Navigate to **S3** → Select your bucket → **Management** tab
2. Click **Create lifecycle rule**
3. **Lifecycle rule configuration:**
   - Rule name: `GDriveBackupLifecycle`
   - Status: "Enabled"
   - Rule scope: "Apply to all objects in the bucket"
   
4. **Lifecycle rule actions:**
   - Check "Transition current versions of objects between storage classes"
   
5. **Transition current versions:**
   - Click **Add transition**
     - Days after object creation: `30`
     - Storage class: `Standard-IA`
   - Click **Add transition**
     - Days after object creation: `90`
     - Storage class: `Glacier Flexible Retrieval`
   - Click **Add transition**
     - Days after object creation: `365`
     - Storage class: `Glacier Deep Archive`
   
6. Review and click **Create rule**

### 2.4 Store Google Credentials in AWS Secrets Manager

**AWS Console Steps:**

1. Navigate to **Secrets Manager** → **Store a new secret**
2. **Secret type:**
   - Select "Other type of secret"
   - For "Key/value pairs", select "Plaintext" tab
   
3. **Paste your Google service account JSON:**
   - Open your downloaded service account JSON file in a text editor
   - Copy the entire contents
   - Paste into the plaintext field
   - Click **Next**
   
4. **Configure secret:**
   - Secret name: `gdrive-backup-credentials`
   - Description: `Google Service Account for GDrive Backup`
   - Click **Next**
   
5. **Configure rotation:** (Optional)
   - For now, leave "Disable automatic rotation" selected
   - Click **Next**
   
6. Review and click **Store**

### 2.5 Create IAM Role for Lambda

**AWS Console Steps:**

1. Navigate to **IAM** → **Roles** → **Create role**

2. **Select trusted entity:**
   - Trusted entity type: "AWS service"
   - Use case: "Lambda"
   - Click **Next**

3. **Add permissions - Built-in policy:**
   - Search for and select: `AWSLambdaBasicExecutionRole`
   - This provides CloudWatch Logs permissions
   - Click **Next** (we'll add custom permissions after)

4. **Name, review, and create:**
   - Role name: `gdrive-backup-lambda-role`
   - Description: `Execution role for Google Drive backup Lambda function`
   - Click **Create role**

5. **Add custom inline policy:**
   - Click on the role name you just created
   - Go to **Permissions** tab → **Add permissions** → **Create inline policy**
   - Click **JSON** tab and paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": [
        "arn:aws:s3:::your-gdrive-backup-bucket",
        "arn:aws:s3:::your-gdrive-backup-bucket/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:gdrive-backup-credentials-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:GenerateDataKey"
      ],
      "Resource": "arn:aws:kms:*:*:key/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

6. **Review and create policy:**
   - Replace `your-gdrive-backup-bucket` with your actual bucket name
   - Click **Review policy**
   - Policy name: `gdrive-backup-policy`
   - Click **Create policy**

### 2.6 Create Lambda Layer for Dependencies

**Local Preparation (on your computer):**

1. Create a directory structure and install dependencies:
```bash
mkdir -p lambda-layer/python
pip install --target lambda-layer/python \
  google-api-python-client==2.95.0 \
  google-auth==2.22.0 \
  google-auth-httplib2==0.1.0
```

2. Create a ZIP file:
```bash
cd lambda-layer
zip -r ../gdrive-backup-layer.zip .
cd ..
```

**AWS Console Steps:**

1. Navigate to **Lambda** → **Layers** → **Create layer**

2. **Configure layer:**
   - Name: `gdrive-backup-dependencies`
   - Description: `Google API dependencies for GDrive backup`
   - Upload: Choose "Upload a .zip file"
   - Click **Upload** and select your `gdrive-backup-layer.zip` file
   - Compatible architectures: Select "x86_64"
   - Compatible runtimes: Select "Python 3.9"

3. Click **Create**

**Note:** Save the Layer ARN shown after creation - you'll need it for the Lambda function

### 2.7 Deploy Lambda Function

**Local Preparation:**

1. Prepare the Lambda code:
   - Copy the `gdrive.py` file from `lambda/google-drive-backup/` directory
   - Rename it to `lambda_function.py` (or keep as `gdrive.py` and adjust handler)
   - Create a ZIP file containing the code

**AWS Console Steps:**

1. Navigate to **Lambda** → **Functions** → **Create function**

2. **Basic information:**
   - Function name: `gdrive-backup`
   - Runtime: "Python 3.9"
   - Architecture: "x86_64"
   - Permissions: "Use an existing role"
   - Existing role: Select `gdrive-backup-lambda-role`
   - Click **Create function**

3. **Upload code:**
   - In the "Code" tab, click **Upload from** → **.zip file**
   - Upload your code ZIP file
   - Click **Save**

4. **Configuration - General:**
   - Click **Configuration** tab → **General configuration** → **Edit**
   - Memory: `512 MB` (or more for large files)
   - Timeout: `5 min 0 sec` (300 seconds)
   - Click **Save**

5. **Configuration - Environment variables:**
   - Click **Environment variables** → **Edit**
   - Add the following variables:
     - `S3_BUCKET` = `your-gdrive-backup-bucket`
     - `SECRET_NAME` = `gdrive-backup-credentials`
     - `MAX_WORKERS` = `5`
     - `ENABLE_SHARED_DRIVES` = `true`
     - `RATE_LIMIT_DELAY` = `0.05`
     - `LARGE_FILE_THRESHOLD` = `104857600`
   - Click **Save**

6. **Add Layer:**
   - Scroll down to "Layers" section → **Add a layer**
   - Choose "Custom layers"
   - Select `gdrive-backup-dependencies` from dropdown
   - Version: Select the latest version
   - Click **Add**

7. **Update Handler (if needed):**
   - In **Runtime settings** → **Edit**
   - Handler: `gdrive.lambda_handler` (or `lambda_function.lambda_handler` if renamed)
   - Click **Save**

### 2.8 (Optional) Create DynamoDB Table for Incremental Backups

**AWS Console Steps:**

1. Navigate to **DynamoDB** → **Tables** → **Create table**

2. **Table details:**
   - Table name: `gdrive-backup-state`
   - Partition key: `file_id` (String)
   - No sort key needed
   - Table settings: "Customize settings"

3. **Table class:**
   - Keep "DynamoDB Standard"

4. **Capacity settings:**
   - Capacity mode: "On-demand" (pay per request)
   - This automatically scales with your usage

5. Click **Create table**

6. **Enable TTL (Time to Live):**
   - After table is created, click on the table name
   - Go to **Additional settings** tab
   - In "Time to Live (TTL)" section, click **Manage**
   - Enable TTL
   - TTL attribute: `ttl`
   - Click **Save**

7. **Update Lambda Role Permissions:**
   - Navigate to **IAM** → **Roles** → Select `gdrive-backup-lambda-role`
   - Click on your inline policy → **Edit policy**
   - Add this statement to the JSON:
```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem"
  ],
  "Resource": "arn:aws:dynamodb:*:*:table/gdrive-backup-state"
}
```
   - Click **Review policy** → **Save changes**

8. **Add DynamoDB Table to Lambda Environment:**
   - Go back to your Lambda function
   - **Configuration** → **Environment variables** → **Edit**
   - Add: `DYNAMODB_TABLE` = `gdrive-backup-state`
   - Click **Save**

## Step 3: Testing the Setup

### 3.1 Manual Lambda Invocation

**AWS Console Steps:**

1. Navigate to **Lambda** → Select your `gdrive-backup` function

2. **Test the function:**
   - Click **Test** button
   - Configure test event:
     - Event name: `TestBackup`
     - Event JSON: `{}` (empty object)
   - Click **Create**
   - Click **Test** again to run

3. **View results:**
   - Execution results will show below
   - Check "Response" for success/error
   - Click "Details" to see full output

4. **View logs:**
   - Click **Monitor** tab → **View CloudWatch logs**
   - Or navigate to **CloudWatch** → **Log groups** → `/aws/lambda/gdrive-backup`
   - Click on the latest log stream
   - Review execution logs for any errors

### 3.2 Verify S3 Backup

**AWS Console Steps:**

1. Navigate to **S3** → Select your backup bucket

2. **Browse backed up files:**
   - You should see folders organized by user email
   - Navigate through the folder structure
   - Click on any file to view details

3. **Check file properties:**
   - Select a file → Click **Properties** tab
   - Verify encryption status
   - Check metadata for original file information

## Step 4: (Optional) Schedule Automatic Backups

**AWS Console Steps:**

1. Navigate to **EventBridge** → **Rules** → **Create rule**

2. **Define rule detail:**
   - Name: `gdrive-backup-schedule`
   - Description: `Daily Google Drive backup schedule`
   - Event bus: "default"
   - Rule type: "Schedule"
   - Click **Next**

3. **Define schedule:**
   - Schedule pattern: "A schedule that runs at a regular rate"
   - Rate expression: Choose "Cron-based schedule"
   - Cron expression: `0 2 * * ? *` (daily at 2 AM UTC)
   - Or use "Rate-based schedule" for simpler options (e.g., "1 day")
   - Click **Next**

4. **Select targets:**
   - Target type: "AWS service"
   - Select a target: "Lambda function"
   - Function: Select `gdrive-backup`
   - Click **Next**

5. **Configure tags:** (Optional)
   - Add any tags if needed
   - Click **Next**

6. **Review and create:**
   - Review all settings
   - Click **Create rule**

**Note:** The Lambda function will automatically be granted permission to be invoked by EventBridge.

## Troubleshooting

### Common Issues

1. **Authentication Errors**
   - Verify service account has access to Google Drive
   - Check Secrets Manager secret contains valid JSON
   - Ensure Lambda can access Secrets Manager

2. **S3 Access Denied**
   - Verify Lambda role has S3 permissions
   - Check bucket name in environment variables
   - Ensure KMS key permissions if using encryption

3. **Timeout Issues**
   - Increase Lambda timeout (max 15 minutes)
   - Reduce MAX_WORKERS for large files
   - Consider breaking up large drives into multiple functions

4. **Rate Limiting**
   - Increase RATE_LIMIT_DELAY
   - Reduce MAX_WORKERS
   - Implement exponential backoff

### Monitoring

- CloudWatch Logs: `/aws/lambda/gdrive-backup`
- CloudWatch Metrics: Custom namespace `GDriveBackup`
- S3 Bucket metrics for storage usage

## Cost Considerations

- **Lambda**: ~$0.20 per 1M requests + compute time
- **S3 Storage**: 
  - Standard: ~$0.023/GB/month
  - IA: ~$0.0125/GB/month (after 30 days)
  - Glacier: ~$0.004/GB/month (after 90 days)
  - Deep Archive: ~$0.00099/GB/month (after 365 days)
- **Data Transfer**: First 1GB free, then ~$0.09/GB
- **Secrets Manager**: $0.40/secret/month

## Security Best Practices

1. Use least-privilege IAM policies
2. Enable S3 bucket encryption
3. Rotate service account keys regularly
4. Monitor CloudWatch logs for unauthorized access
5. Use VPC endpoints if running in VPC
6. Enable CloudTrail for audit logging

## Next Steps

- Set up CloudWatch alarms for failures
- Implement backup verification
- Create restore procedures
- Document specific Google Drive IDs/paths being backed up