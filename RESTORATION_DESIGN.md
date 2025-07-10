# Google Drive Restoration System Design

## Overview

A web-based dashboard for browsing S3 backups and restoring files to Google Drive.

## Architecture Components

### 1. Flask Web Application
- Browse S3 backup structure
- Search and filter files
- Preview file metadata
- Initiate restore operations
- Monitor restore progress

### 2. Backend API Endpoints

```python
/api/backups
  - GET: List all backup dates and users

/api/backups/{user}/{date}
  - GET: List files for specific backup

/api/backups/{user}/{date}/tree
  - GET: Folder tree structure

/api/restore
  - POST: Restore selected files
  - Body: {
      "files": ["s3_key1", "s3_key2"],
      "destination": "original" | "new_folder",
      "target_email": "user@domain.com"
    }

/api/restore/{job_id}
  - GET: Check restore job status

/api/preview/{s3_key}
  - GET: Preview file (images, text, metadata)
```

### 3. Restore Lambda Function

New Lambda function `gdrive-restore` that:
- Reads files from S3
- Uploads to Google Drive
- Handles Google Workspace conversion
- Maintains folder structure
- Updates DynamoDB with restore status

### 4. Database Schema

**Restore Jobs Table (DynamoDB):**
```
restore_jobs
- job_id (PK)
- user_email
- status (pending|in_progress|completed|failed)
- files_total
- files_completed
- created_at
- completed_at
- error_message
```

## Implementation Plan

### Phase 1: Core Restore Function

```python
# restore.py - Lambda function
def restore_file_to_drive(s3_key, target_email, destination_folder=None):
    """
    Restore a single file from S3 to Google Drive
    """
    # Download from S3
    file_content = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
    metadata = file_content['Metadata']
    
    # Create Google Drive service with write permissions
    service = get_drive_service_for_user(target_email)
    
    # Determine mime type and conversion
    original_mime = metadata.get('mime-type')
    file_name = s3_key.split('/')[-1]
    
    # Handle conversions (PDF -> Google Doc, etc.)
    if file_name.endswith('.pdf') and original_mime == 'application/vnd.google-apps.document':
        # Convert back to Google Doc
        mime_type = 'application/vnd.google-apps.document'
    
    # Create file metadata
    file_metadata = {
        'name': file_name.replace('.pdf', '').replace('.xlsx', ''),
        'mimeType': mime_type
    }
    
    if destination_folder:
        file_metadata['parents'] = [destination_folder]
    
    # Upload to Drive
    media = MediaIoBaseUpload(io.BytesIO(file_content['Body'].read()),
                             mimetype=original_mime)
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    
    return file.get('id')
```

### Phase 2: Flask Dashboard

```python
# app.py - Flask application
from flask import Flask, render_template, jsonify, request
import boto3

app = Flask(__name__)

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/backups')
def list_backups():
    """List all available backups grouped by user and date"""
    s3 = boto3.client('s3')
    
    # List all prefixes (users)
    paginator = s3.get_paginator('list_objects_v2')
    users = set()
    
    for page in paginator.paginate(Bucket=S3_BUCKET, Delimiter='/'):
        for prefix in page.get('CommonPrefixes', []):
            users.add(prefix['Prefix'].rstrip('/'))
    
    # For each user, get backup dates
    backups = {}
    for user in users:
        dates = set()
        for page in paginator.paginate(
            Bucket=S3_BUCKET, 
            Prefix=f"{user}/",
            Delimiter='/'
        ):
            for prefix in page.get('CommonPrefixes', []):
                date = prefix['Prefix'].split('/')[-2]
                if date.startswith('20'):  # Is a date
                    dates.add(date)
        
        backups[user] = sorted(list(dates), reverse=True)
    
    return jsonify(backups)

@app.route('/api/backups/<user>/<date>')
def list_backup_files(user, date):
    """List all files in a specific backup"""
    s3 = boto3.client('s3')
    
    files = []
    paginator = s3.get_paginator('list_objects_v2')
    
    for page in paginator.paginate(
        Bucket=S3_BUCKET,
        Prefix=f"{user}/{date}/"
    ):
        for obj in page.get('Contents', []):
            # Get file metadata
            head = s3.head_object(Bucket=S3_BUCKET, Key=obj['Key'])
            
            files.append({
                'key': obj['Key'],
                'size': obj['Size'],
                'last_modified': obj['LastModified'].isoformat(),
                'metadata': head.get('Metadata', {}),
                'path': obj['Key'].replace(f"{user}/{date}/", '')
            })
    
    return jsonify(files)
```

### Phase 3: Dashboard UI

```html
<!-- templates/dashboard.html -->
<!DOCTYPE html>
<html>
<head>
    <title>Google Drive Backup Dashboard</title>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <style>
        .file-browser {
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 20px;
            padding: 20px;
        }
        .file-list {
            border: 1px solid #ddd;
            padding: 10px;
            max-height: 600px;
            overflow-y: auto;
        }
        .file-item {
            padding: 8px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
        }
        .file-item:hover {
            background: #f0f0f0;
        }
        .selected {
            background: #e3f2fd;
        }
        .restore-panel {
            position: fixed;
            bottom: 0;
            right: 0;
            background: white;
            border: 1px solid #ddd;
            padding: 20px;
            box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
        }
    </style>
</head>
<body>
    <div id="app">
        <h1>Google Drive Backup Dashboard</h1>
        
        <div class="file-browser">
            <!-- User/Date Selector -->
            <div>
                <h3>Backups</h3>
                <select v-model="selectedUser" @change="loadDates">
                    <option value="">Select User</option>
                    <option v-for="user in users" :key="user" :value="user">
                        {{ user }}
                    </option>
                </select>
                
                <select v-model="selectedDate" @change="loadFiles" v-if="dates.length">
                    <option value="">Select Date</option>
                    <option v-for="date in dates" :key="date" :value="date">
                        {{ date }}
                    </option>
                </select>
            </div>
            
            <!-- File List -->
            <div class="file-list" v-if="files.length">
                <h3>Files ({{ selectedFiles.length }} selected)</h3>
                <div v-for="file in files" :key="file.key"
                     class="file-item"
                     :class="{selected: isSelected(file)}"
                     @click="toggleSelection(file)">
                    <span>{{ file.path }}</span>
                    <span>{{ formatSize(file.size) }}</span>
                </div>
            </div>
        </div>
        
        <!-- Restore Panel -->
        <div class="restore-panel" v-if="selectedFiles.length">
            <h3>Restore Options</h3>
            <p>{{ selectedFiles.length }} files selected</p>
            
            <label>
                Restore to:
                <input type="email" v-model="targetEmail" placeholder="user@domain.com">
            </label>
            
            <label>
                <input type="radio" v-model="restoreMode" value="original">
                Original location
            </label>
            <label>
                <input type="radio" v-model="restoreMode" value="new_folder">
                New folder
            </label>
            
            <button @click="restore" :disabled="!targetEmail">
                Restore Files
            </button>
        </div>
    </div>

    <script>
    const { createApp } = Vue;
    
    createApp({
        data() {
            return {
                users: [],
                dates: [],
                files: [],
                selectedUser: '',
                selectedDate: '',
                selectedFiles: [],
                targetEmail: '',
                restoreMode: 'original',
                backups: {}
            }
        },
        mounted() {
            this.loadBackups();
        },
        methods: {
            async loadBackups() {
                const response = await fetch('/api/backups');
                this.backups = await response.json();
                this.users = Object.keys(this.backups);
            },
            loadDates() {
                this.dates = this.backups[this.selectedUser] || [];
                this.selectedDate = '';
                this.files = [];
                this.selectedFiles = [];
            },
            async loadFiles() {
                if (!this.selectedUser || !this.selectedDate) return;
                
                const response = await fetch(
                    `/api/backups/${this.selectedUser}/${this.selectedDate}`
                );
                this.files = await response.json();
            },
            toggleSelection(file) {
                const index = this.selectedFiles.findIndex(f => f.key === file.key);
                if (index > -1) {
                    this.selectedFiles.splice(index, 1);
                } else {
                    this.selectedFiles.push(file);
                }
            },
            isSelected(file) {
                return this.selectedFiles.some(f => f.key === file.key);
            },
            formatSize(bytes) {
                const sizes = ['B', 'KB', 'MB', 'GB'];
                if (bytes === 0) return '0 B';
                const i = Math.floor(Math.log(bytes) / Math.log(1024));
                return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i];
            },
            async restore() {
                const payload = {
                    files: this.selectedFiles.map(f => f.key),
                    destination: this.restoreMode,
                    target_email: this.targetEmail
                };
                
                const response = await fetch('/api/restore', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                
                const result = await response.json();
                alert(`Restore job started: ${result.job_id}`);
                this.selectedFiles = [];
            }
        }
    }).mount('#app');
    </script>
</body>
</html>
```

## Additional Features to Consider

### 1. Advanced Search
- Search by filename
- Filter by file type
- Date range selection
- Size filters

### 2. Preview Capabilities
- Image thumbnails
- Text file preview
- PDF preview
- Metadata display

### 3. Bulk Operations
- Select all/none
- Folder selection
- Regex selection

### 4. Restore Options
- Version selection (from S3 versions)
- Conflict resolution (skip/rename/overwrite)
- Folder mapping (restore to different structure)

### 5. Monitoring
- Real-time progress updates
- Email notifications on completion
- Restore history log

### 6. Security
- OAuth authentication
- Role-based access control
- Audit logging
- Restore approval workflow

## Required AWS Changes

### 1. Update Lambda Execution Role

**AWS Console Steps:**
1. Navigate to **IAM** → **Roles** → Select your Lambda execution role
2. Update the inline policy to include Google Drive write permissions
3. When creating the restore Lambda function, ensure it uses appropriate Google API scopes:
   ```python
   scopes=['https://www.googleapis.com/auth/drive.file']
   ```

### 2. API Gateway Setup

**AWS Console Steps:**
1. Navigate to **API Gateway** → **Create API**
2. Choose "REST API" → **Build**
3. API details:
   - API name: `gdrive-restore-api`
   - Description: `REST API for Google Drive restoration dashboard`
4. Create resources and methods for each endpoint:
   - **Resources** → **Create Resource** for each path
   - **Actions** → **Create Method** for GET/POST
   - Integration type: "Lambda Function"
   - Select appropriate Lambda functions
5. **Deploy API**:
   - **Actions** → **Deploy API**
   - Stage name: `prod`

### 3. Host Flask Application

**Option A: AWS App Runner (Easiest)**
1. Navigate to **App Runner** → **Create service**
2. Source: "Source code repository" or "Container image"
3. Configure build settings for Flask app
4. Service settings:
   - Service name: `gdrive-restore-dashboard`
   - Port: `5000` (Flask default)
5. Configure environment variables for API endpoints

**Option B: EC2 Instance**
1. Navigate to **EC2** → **Launch instance**
2. Choose Amazon Linux 2 or Ubuntu
3. Instance type: t3.small or larger
4. Configure security group:
   - Allow HTTP (80) and HTTPS (443)
   - Allow SSH (22) for management
5. After launch, install Python, Flask, and dependencies
6. Deploy application and configure nginx/Apache

**Option C: ECS with Fargate**
1. Navigate to **ECS** → **Create cluster**
2. Create task definition for Flask app
3. Create service with Application Load Balancer
4. Configure auto-scaling as needed

### 4. Create Additional DynamoDB Tables

**AWS Console Steps:**

**Table 1: restore_jobs**
1. Navigate to **DynamoDB** → **Create table**
2. Configuration:
   - Table name: `restore_jobs`
   - Partition key: `job_id` (String)
   - Capacity: On-demand
3. Click **Create table**

**Table 2: restore_history**
1. **Create table**:
   - Table name: `restore_history`
   - Partition key: `user_email` (String)
   - Sort key: `timestamp` (String)
   - Capacity: On-demand

**Table 3: user_permissions**
1. **Create table**:
   - Table name: `user_permissions`
   - Partition key: `user_email` (String)
   - Capacity: On-demand

This design provides a complete restoration solution with a user-friendly interface for browsing and restoring Google Drive backups.