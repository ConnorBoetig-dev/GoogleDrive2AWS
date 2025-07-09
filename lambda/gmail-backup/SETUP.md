# Gmail Backup Lambda Setup Guide

## Prerequisites

1. **Google Cloud Setup**
   - Enable Gmail API in your Google Cloud Project
   - Use existing service account from Google Drive (recommended)
   - OR create new service account with domain-wide delegation

2. **AWS Resources**
   - S3 bucket: `gmail-backup34`
   - DynamoDB table: `gmail-backup-state`
   - Secrets Manager secret with service account JSON
   - IAM role for Lambda execution

## Step 1: Create DynamoDB Table

```bash
aws dynamodb create-table \
    --table-name gmail-backup-state \
    --attribute-definitions AttributeName=messageId,AttributeType=S \
    --key-schema AttributeName=messageId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
```

Enable TTL on the `ttl` field after creation.

## Step 2: Configure Service Account for Gmail

### Option 1: Reuse Existing Google Drive Service Account
1. Go to Google Admin Console → Security → API Controls → Domain-wide Delegation
2. Find your existing service account
3. Add Gmail scopes:
   ```
   https://www.googleapis.com/auth/gmail.readonly
   https://www.googleapis.com/auth/gmail.metadata
   ```

### Option 2: Create New Service Account
1. Create service account in Google Cloud Console
2. Enable domain-wide delegation
3. Add to Google Admin Console with Gmail scopes
4. Store JSON key in same Secrets Manager secret

## Step 3: Create Lambda Function

1. **Function Configuration:**
   - Runtime: Python 3.11
   - Architecture: x86_64
   - Memory: 512 MB (increase for larger attachments)
   - Timeout: 5 minutes
   - Handler: `lambda_function.lambda_handler`

2. **Environment Variables:**
   ```
   S3_BUCKET=gmail-backup34
   SECRET_NAME=your-secret-name
   DYNAMODB_TABLE=gmail-backup-state
   TARGET_EMAIL=user@yourdomain.com
   MAX_MESSAGES_PER_BATCH=50
   RATE_LIMIT_DELAY=0.1
   ```

3. **IAM Role Policy:**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:PutObject",
           "s3:GetObject"
         ],
         "Resource": "arn:aws:s3:::gmail-backup34/*"
       },
       {
         "Effect": "Allow",
         "Action": [
           "dynamodb:GetItem",
           "dynamodb:PutItem",
           "dynamodb:UpdateItem"
         ],
         "Resource": "arn:aws:dynamodb:*:*:table/gmail-backup-state"
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
           "logs:CreateLogGroup",
           "logs:CreateLogStream",
           "logs:PutLogEvents"
         ],
         "Resource": "*"
       }
     ]
   }
   ```

## Step 4: Deploy Code

1. **Package dependencies:**
   ```bash
   pip install -r requirements.txt -t .
   zip -r gmail-backup.zip .
   ```

2. **Upload to Lambda:**
   ```bash
   aws lambda update-function-code \
       --function-name gmail-backup \
       --zip-file fileb://gmail-backup.zip
   ```

## Step 5: Create EventBridge Rule (Optional)

For scheduled backups:
```bash
aws events put-rule \
    --name gmail-backup-schedule \
    --schedule-expression "rate(1 day)"

aws events put-targets \
    --rule gmail-backup-schedule \
    --targets "Id"="1","Arn"="arn:aws:lambda:region:account:function:gmail-backup"
```

## Usage

### Manual Invocation

```bash
# Backup INBOX (default)
aws lambda invoke \
    --function-name gmail-backup \
    response.json

# Backup with custom query
aws lambda invoke \
    --function-name gmail-backup \
    --payload '{"query": "label:SENT", "max_messages": 100}' \
    response.json
```

### Event Payload Options

```json
{
  "query": "label:INBOX is:unread",  // Gmail search query
  "max_messages": 100                 // Max messages per execution
}
```

## Folder Structure in S3

```
gmail-backup34/
├── user@example.com/
│   ├── 2024/
│   │   ├── 01/
│   │   │   ├── 15/
│   │   │   │   ├── message-id-1.eml
│   │   │   │   └── message-id-2.eml
│   └── attachments/
│       └── 2024/
│           └── 01/
│               └── 15/
│                   ├── message-id-1/
│                   │   ├── document.pdf
│                   │   └── image.jpg
```

## Monitoring

- Check CloudWatch Logs for execution details
- Monitor DynamoDB for backup status
- Use S3 lifecycle policies for cost optimization

## Limitations

- Gmail API quota: 250 quota units per user per second
- Attachment size limited by Lambda memory
- OAuth tokens expire and need refresh

## Getting OAuth Refresh Token

Use this Python script to obtain refresh token:

```python
from google_auth_oauthlib.flow import Flow

# Configure with your OAuth credentials
flow = Flow.from_client_config(
    {
        "installed": {
            "client_id": "your-client-id",
            "client_secret": "your-client-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    },
    scopes=['https://www.googleapis.com/auth/gmail.readonly']
)

flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'

auth_url, _ = flow.authorization_url(
    access_type='offline',
    include_granted_scopes='true'
)

print(f"Visit this URL: {auth_url}")
code = input("Enter the authorization code: ")

flow.fetch_token(code=code)
print(f"Refresh token: {flow.credentials.refresh_token}")
```