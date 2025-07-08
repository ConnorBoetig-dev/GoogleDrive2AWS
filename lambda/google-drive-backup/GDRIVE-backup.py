import json
import boto3
import os
import logging
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import io

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

# Environment variables
S3_BUCKET = os.environ['S3_BUCKET']
SECRET_NAME = os.environ['SECRET_NAME']

def get_google_drive_service():
    """Get Google Drive service using credentials from Secrets Manager"""
    try:
        # Get credentials from Secrets Manager
        logger.info("Getting credentials from Secrets Manager...")
        response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
        credentials_json = json.loads(response['SecretString'])
        
        # Create credentials
        credentials = service_account.Credentials.from_service_account_info(
            credentials_json,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        
        # Build the service
        service = build('drive', 'v3', credentials=credentials)
        logger.info("Google Drive service created successfully")
        return service
        
    except Exception as e:
        logger.error(f"Error getting Google Drive service: {str(e)}")
        raise

def list_shared_files(service):
    """List all files and folders shared with the service account"""
    try:
        all_files = []
        page_token = None
        
        logger.info("Listing all files shared with service account...")
        
        while True:
            # Query for all files the service account has access to
            # This will include both directly shared files and files in shared folders
            results = service.files().list(
                pageSize=100,
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, parents, shared)",
                pageToken=page_token,
                q="trashed=false"  # Exclude trashed files
            ).execute()
            
            files = results.get('files', [])
            all_files.extend(files)
            
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        
        logger.info(f"Found {len(all_files)} total files/folders shared with service account")
        
        # Filter to only include files (not folders)
        files_only = [f for f in all_files if f['mimeType'] != 'application/vnd.google-apps.folder']
        logger.info(f"Found {len(files_only)} files to backup")
        
        return files_only
        
    except HttpError as e:
        logger.error(f"Error listing files: {str(e)}")
        return []

def get_file_path(service, file_id, file_name):
    """Get the full path of a file including parent folders"""
    try:
        path_parts = [file_name]
        
        # Get file metadata to check for parents
        file_metadata = service.files().get(
            fileId=file_id,
            fields='parents'
        ).execute()
        
        parents = file_metadata.get('parents', [])
        
        # Traverse up the folder hierarchy
        while parents:
            parent_id = parents[0]
            try:
                parent_metadata = service.files().get(
                    fileId=parent_id,
                    fields='name, parents'
                ).execute()
                path_parts.insert(0, parent_metadata['name'])
                parents = parent_metadata.get('parents', [])
            except:
                # If we can't access the parent, stop traversing
                break
        
        return '/'.join(path_parts)
        
    except Exception as e:
        logger.warning(f"Could not determine full path for {file_name}, using filename only")
        return file_name

def download_file(service, file_id, file_name, mime_type):
    """Download a file from Google Drive"""
    try:
        logger.info(f"Downloading file: {file_name}")
        
        # Handle Google Workspace documents (need to be exported)
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
            # Regular file download
            request = service.files().get_media(fileId=file_id)
        
        # Download the file
        file_io = io.BytesIO()
        downloader = request.execute()
        file_io.write(downloader)
        file_io.seek(0)
        
        logger.info(f"Successfully downloaded: {file_name}")
        return file_io.getvalue(), file_name
        
    except HttpError as e:
        logger.error(f"Error downloading file {file_name}: {str(e)}")
        return None, None

def upload_to_s3(content, s3_key):
    """Upload content to S3"""
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=content,
            ServerSideEncryption='aws:kms'
        )
        logger.info(f"Successfully uploaded to S3: {s3_key}")
        return True
        
    except Exception as e:
        logger.error(f"Error uploading to S3: {str(e)}")
        return False

def lambda_handler(event, context):
    """Main Lambda handler"""
    try:
        logger.info("Starting Google Drive backup process...")
        
        # Get Google Drive service
        service = get_google_drive_service()
        
        # List all files shared with the service account
        files = list_shared_files(service)
        
        if not files:
            logger.warning("No files found to backup")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No files found to backup',
                    'files_processed': 0
                })
            }
        
        # Process each file
        successful_uploads = 0
        failed_uploads = 0
        
        for file in files:
            file_name = file['name']
            file_id = file['id']
            mime_type = file['mimeType']
            
            logger.info(f"Processing file: {file_name} (type: {mime_type})")
            
            # Get the full path including folders
            file_path = get_file_path(service, file_id, file_name)
            
            # Download file
            file_content, final_name = download_file(service, file_id, file_name, mime_type)
            
            if file_content and final_name:
                # Create S3 key with timestamp and preserve folder structure
                timestamp = datetime.now().strftime('%Y-%m-%d')
                # Replace the filename in the path with the final name (which includes extension)
                path_parts = file_path.split('/')
                path_parts[-1] = final_name
                full_path = '/'.join(path_parts)
                s3_key = f"gdrive-backup/{timestamp}/{full_path}"
                
                # Upload to S3
                if upload_to_s3(file_content, s3_key):
                    successful_uploads += 1
                else:
                    failed_uploads += 1
            else:
                failed_uploads += 1
        
        logger.info(f"Backup completed. Successful: {successful_uploads}, Failed: {failed_uploads}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Google Drive backup completed',
                'files_processed': len(files),
                'successful_uploads': successful_uploads,
                'failed_uploads': failed_uploads
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