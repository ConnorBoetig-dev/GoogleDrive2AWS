import json
import boto3
import os
import logging
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import io
import time
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')
cloudwatch = boto3.client('cloudwatch')

# Environment variables
S3_BUCKET = os.environ['S3_BUCKET']
SECRET_NAME = os.environ['SECRET_NAME']

def get_google_drive_service():
    """Get Google Drive service using credentials from Secrets Manager"""
    try:
        logger.info("Getting credentials from Secrets Manager...")
        response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
        credentials_json = json.loads(response['SecretString'])
        
        credentials = service_account.Credentials.from_service_account_info(
            credentials_json,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        
        service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        logger.info("Google Drive service created successfully")
        return service
        
    except Exception as e:
        logger.error(f"Error getting Google Drive service: {str(e)}")
        raise

def get_file_owner(service, file_id):
    """Get the owner email of a file"""
    try:
        file_metadata = service.files().get(
            fileId=file_id,
            fields='owners'
        ).execute()
        
        owners = file_metadata.get('owners', [])
        if owners:
            return owners[0].get('emailAddress', 'unknown')
        
        return 'shared'
        
    except Exception as e:
        logger.warning(f"Could not get owner for file {file_id}: {e}")
        return 'unknown'

def list_shared_files_by_user(service):
    """List all files shared with service account, organized by user"""
    try:
        files_by_user = {}
        page_token = None
        
        logger.info("Listing all files shared with service account...")
        
        while True:
            try:
                results = service.files().list(
                    pageSize=100,
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, owners)",
                    pageToken=page_token,
                    q="trashed=false"
                ).execute()
                
                files = results.get('files', [])
                
                for file in files:
                    # Skip folders
                    if file.get('mimeType') == 'application/vnd.google-apps.folder':
                        continue
                    
                    # Get file owner from the owners field directly
                    owners = file.get('owners', [])
                    if owners:
                        owner_email = owners[0].get('emailAddress', 'unknown')
                    else:
                        owner_email = 'shared'
                    
                    # Organize by owner
                    if owner_email not in files_by_user:
                        files_by_user[owner_email] = []
                    
                    files_by_user[owner_email].append(file)
                
                page_token = results.get('nextPageToken')
                if not page_token:
                    break
                    
            except Exception as e:
                logger.error(f"Error in pagination: {str(e)}")
                break
        
        # Log summary
        for user, user_files in files_by_user.items():
            logger.info(f"User {user}: {len(user_files)} files")
        
        return files_by_user
        
    except HttpError as e:
        logger.error(f"Error listing files: {str(e)}")
        return {}

def get_file_path(service, file_id, file_name):
    """Get the full path of a file including parent folders"""
    try:
        # For now, just return the filename to avoid additional API calls
        # This can be enhanced later if needed
        return file_name
        
    except Exception as e:
        logger.warning(f"Could not determine full path for {file_name}, using filename only")
        return file_name

def download_file(service, file_id, file_name, mime_type):
    """Download a file from Google Drive with retry logic"""
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Downloading file: {file_name} (attempt {attempt + 1})")
            
            # Handle Google Workspace documents
            if mime_type.startswith('application/vnd.google-apps'):
                if mime_type == 'application/vnd.google-apps.document':
                    export_mime_type = 'application/pdf'
                    file_name += '.pdf'
                elif mime_type == 'application/vnd.google-apps.spreadsheet':
                    export_mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    file_name += '.xlsx'
                elif mime_type == 'application/vnd.google-apps.presentation':
                    export_mime_type = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                    file_name += '.pptx'
                elif mime_type == 'application/vnd.google-apps.drawing':
                    export_mime_type = 'application/pdf'
                    file_name += '.pdf'
                else:
                    logger.info(f"Skipping unsupported Google Workspace file type: {mime_type}")
                    return None, None
                    
                request = service.files().export_media(fileId=file_id, mimeType=export_mime_type)
            else:
                request = service.files().get_media(fileId=file_id)
            
            # Download with proper error handling
            file_content = request.execute()
            
            logger.info(f"Successfully downloaded: {file_name}")
            return file_content, file_name
            
        except Exception as e:
            logger.error(f"Error downloading file {file_name} (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                return None, None

def upload_to_s3(content, s3_key, metadata):
    """Upload content to S3 with retry logic"""
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=content,
                ServerSideEncryption='aws:kms',
                Metadata=metadata
            )
            logger.info(f"Successfully uploaded to S3: {s3_key}")
            return True
            
        except ClientError as e:
            logger.error(f"Error uploading to S3 (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                return False

def process_single_file(service, file, owner_email, backup_date):
    """Process a single file for backup"""
    file_name = file['name']
    file_id = file['id']
    mime_type = file.get('mimeType', 'application/octet-stream')
    
    try:
        logger.info(f"Processing: {file_name} (owner: {owner_email}, type: {mime_type})")
        
        # Download file
        file_content, final_name = download_file(service, file_id, file_name, mime_type)
        
        if not file_content or not final_name:
            return False, 0
        
        # Get file path
        file_path = get_file_path(service, file_id, final_name)
        
        # Create S3 key with user organization
        # Format: gdrive-backup/{username}/{YYYY-MM-DD}/{file_path}
        # Extract username from email (everything before @)
        username = owner_email.split('@')[0] if '@' in owner_email else owner_email
        s3_key = f"gdrive-backup/{username}/{backup_date}/{file_path}"
        
        # Prepare metadata
        metadata = {
            'original-owner': owner_email,
            'backup-date': backup_date,
            'source-file-id': file_id,
            'mime-type': mime_type
        }
        
        # Upload to S3
        if upload_to_s3(file_content, s3_key, metadata):
            return True, len(file_content) if isinstance(file_content, bytes) else len(file_content.encode('utf-8'))
        else:
            return False, 0
        
    except Exception as e:
        logger.error(f"Error processing {file_name}: {str(e)}")
        return False, 0

def send_metrics(user_email, file_count, success_count, total_bytes):
    """Send metrics to CloudWatch"""
    try:
        namespace = 'GDriveBackup'
        
        cloudwatch.put_metric_data(
            Namespace=namespace,
            MetricData=[
                {
                    'MetricName': 'FilesProcessed',
                    'Value': file_count,
                    'Unit': 'Count',
                    'Dimensions': [{'Name': 'UserEmail', 'Value': user_email}]
                },
                {
                    'MetricName': 'FilesSuccess',
                    'Value': success_count,
                    'Unit': 'Count',
                    'Dimensions': [{'Name': 'UserEmail', 'Value': user_email}]
                },
                {
                    'MetricName': 'BytesBackedUp',
                    'Value': total_bytes,
                    'Unit': 'Bytes',
                    'Dimensions': [{'Name': 'UserEmail', 'Value': user_email}]
                }
            ]
        )
    except Exception as e:
        logger.error(f"Error sending metrics: {e}")

def lambda_handler(event, context):
    """Main Lambda handler"""
    try:
        logger.info("Starting Google Drive backup process...")
        
        # Get backup date
        backup_date = datetime.now().strftime('%Y-%m-%d')
        
        # Get Google Drive service
        service = get_google_drive_service()
        
        # List all files organized by user
        files_by_user = list_shared_files_by_user(service)
        
        if not files_by_user:
            logger.warning("No files found to backup")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No files found to backup',
                    'users_processed': 0,
                    'total_files': 0
                })
            }
        
        # Process files for each user
        overall_stats = {
            'users_processed': 0,
            'total_files': 0,
            'total_success': 0,
            'total_failed': 0,
            'total_bytes': 0,
            'user_summaries': {}
        }
        
        for owner_email, user_files in files_by_user.items():
            logger.info(f"Processing {len(user_files)} files for user: {owner_email}")
            
            user_success = 0
            user_failed = 0
            user_bytes = 0
            
            # Process files sequentially to avoid SSL issues
            for file in user_files:
                try:
                    success, bytes_processed = process_single_file(service, file, owner_email, backup_date)
                    if success:
                        user_success += 1
                        user_bytes += bytes_processed
                    else:
                        user_failed += 1
                except Exception as e:
                    logger.error(f"Failed to process file {file.get('name', 'unknown')}: {str(e)}")
                    user_failed += 1
                
                # Small delay to prevent rate limiting
                time.sleep(0.1)
            
            # Update overall stats
            overall_stats['users_processed'] += 1
            overall_stats['total_files'] += len(user_files)
            overall_stats['total_success'] += user_success
            overall_stats['total_failed'] += user_failed
            overall_stats['total_bytes'] += user_bytes
            overall_stats['user_summaries'][owner_email] = {
                'files': len(user_files),
                'success': user_success,
                'failed': user_failed,
                'bytes': user_bytes
            }
            
            # Send metrics for this user
            send_metrics(owner_email, len(user_files), user_success, user_bytes)
        
        logger.info(f"Backup completed. Users: {overall_stats['users_processed']}, "
                   f"Files: {overall_stats['total_success']}/{overall_stats['total_files']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Google Drive backup completed',
                'statistics': overall_stats
            })
        }
        
    except Exception as e:
        logger.error(f"Error in backup process: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }