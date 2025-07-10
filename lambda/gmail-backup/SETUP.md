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

**AWS Console Steps:**

1. Navigate to **DynamoDB** → **Tables** → **Create table**
2. Table configuration:
   - Table name: `gmail-backup-state`
   - Partition key: `messageId` (String)
   - Table settings: "Customize settings"
   - Capacity mode: "On-demand"
3. Click **Create table**
4. After creation:
   - Click on the table name
   - Go to **Additional settings** tab
   - In "Time to Live" section, click **Manage**
   - Enable TTL on attribute: `ttl`
   - Click **Save**

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

**AWS Console Steps:**

1. **Create the function:**
   - Navigate to **Lambda** → **Functions** → **Create function**
   - Function name: `gmail-backup`
   - Runtime: "Python 3.11"
   - Architecture: "x86_64"
   - Permissions: "Create a new role with basic Lambda permissions"
   - Click **Create function**

2. **Configure function settings:**
   - Go to **Configuration** tab → **General configuration** → **Edit**
   - Memory: `512 MB` (increase for larger attachments)
   - Timeout: `5 minutes`
   - Click **Save**

3. **Add Environment Variables:**
   - **Configuration** → **Environment variables** → **Edit**
   - Add these variables:
     - `S3_BUCKET` = `gmail-backup34`
     - `SECRET_NAME` = `your-secret-name`
     - `DYNAMODB_TABLE` = `gmail-backup-state`
     - `TARGET_EMAIL` = `user@yourdomain.com`
     - `MAX_MESSAGES_PER_BATCH` = `50`
     - `RATE_LIMIT_DELAY` = `0.1`
   - Click **Save**

4. **Update IAM Role:**
   - Click on the execution role link (under Configuration → Permissions)
   - This opens IAM console
   - Click **Add permissions** → **Create inline policy**
   - Click **JSON** tab and paste:

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
    }
  ]
}
```

   - Click **Review policy**
   - Name: `gmail-backup-policy`
   - Click **Create policy**

## Step 4: Deploy Code

**Local preparation:**
1. Package dependencies:
   ```bash
   pip install -r requirements.txt -t .
   zip -r gmail-backup.zip .
   ```

**AWS Console Steps:**
1. Navigate to **Lambda** → Select `gmail-backup` function
2. In the **Code** tab:
   - Click **Upload from** → **.zip file**
   - Click **Upload** and select your `gmail-backup.zip`
   - Click **Save**

## Step 5: Create EventBridge Rule (Optional)

**AWS Console Steps for scheduled backups:**

1. Navigate to **EventBridge** → **Rules** → **Create rule**
2. Rule details:
   - Name: `gmail-backup-schedule`
   - Description: `Daily Gmail backup`
   - Event bus: "default"
   - Rule type: "Schedule"
   - Click **Next**
3. Schedule pattern:
   - "A schedule that runs at a regular rate"
   - Rate expression: Every `1` day(s)
   - Click **Next**
4. Select targets:
   - Target: "Lambda function"
   - Function: `gmail-backup`
   - Click **Next**
5. Review and click **Create rule**

## Usage

### Manual Invocation

**AWS Console Steps:**

1. Navigate to **Lambda** → Select `gmail-backup` function
2. Click **Test** button
3. Configure test event:
   - Event name: `TestINBOX` (for default INBOX backup)
   - Event JSON: `{}` (empty object)
   - Or for custom query:
     ```json
     {
       "query": "label:SENT",
       "max_messages": 100
     }
     ```
4. Click **Create** then **Test**
5. View execution results and logs

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