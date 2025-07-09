import json
import boto3
import os
import logging
import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
import io
import time
from botocore.exceptions import ClientError
from decimal import Decimal

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')
cloudwatch = boto3.client('cloudwatch')
dynamodb = boto3.resource('dynamodb')

# Environment variables
S3_BUCKET = os.environ['S3_BUCKET']
SECRET_NAME = os.environ['SECRET_NAME']
DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE', 'gdrive-backup-state')
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '3'))  # Reduced to prevent SSL issues
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', '50'))
ENABLE_SHARED_DRIVES = os.environ.get('ENABLE_SHARED_DRIVES', 'true').lower() == 'true'
RATE_LIMIT_DELAY = float(os.environ.get('RATE_LIMIT_DELAY', '0.05'))
LARGE_FILE_THRESHOLD = int(os.environ.get('LARGE_FILE_THRESHOLD', '104857600'))  # 100MB

# DynamoDB table for tracking file states
file_state_table = dynamodb.Table(DYNAMODB_TABLE)

# Global credentials cache to avoid repeated Secrets Manager calls
_cached_credentials = None

def get_google_drive_credentials():
    """Get Google Drive credentials from Secrets Manager (cached)"""
    global _cached_credentials
    
    if _cached_credentials is None:
        try:
            logger.info("Getting credentials from Secrets Manager...")
            response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
            credentials_json = json.loads(response['SecretString'])
            
            _cached_credentials = service_account.Credentials.from_service_account_info(
                credentials_json,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
            logger.info("Google Drive credentials cached successfully")
            
        except Exception as e:
            logger.error(f"Error getting Google Drive credentials: {str(e)}")
            raise
    
    return _cached_credentials

def get_google_drive_service():
    """Get Google Drive service using cached credentials"""
    try:
        credentials = get_google_drive_credentials()
        service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        return service
        
    except Exception as e:
        logger.error(f"Error creating Google Drive service: {str(e)}")
        raise

def calculate_file_hash(content):
    """Calculate SHA256 hash of file content"""
    if isinstance(content, str):
        content = content.encode('utf-8')
    return hashlib.sha256(content).hexdigest()

def get_file_state(file_id):
    """Get file state from DynamoDB"""
    try:
        response = file_state_table.get_item(
            Key={'file_id': file_id}
        )
        return response.get('Item')
    except Exception as e:
        logger.warning(f"Error getting file state: {e}")
        return None

def update_file_state(file_id, file_hash, modified_time, s3_key, file_size, drive_md5_checksum=None):
    """Update file state in DynamoDB with Google Drive metadata"""
    try:
        item = {
            'file_id': file_id,
            'file_hash': file_hash,
            'modified_time': modified_time,
            's3_key': s3_key,
            'file_size': Decimal(str(file_size)),
            'last_backup': datetime.now().isoformat(),
            'ttl': int((datetime.now().timestamp() + 30 * 24 * 3600))  # 30 day TTL
        }
        
        # Add Google Drive metadata if available
        if drive_md5_checksum:
            item['drive_md5_checksum'] = drive_md5_checksum
        
        file_state_table.put_item(Item=item)
    except Exception as e:
        logger.error(f"Error updating file state: {e}")

def should_backup_file(file_id, file_hash, modified_time, drive_md5_checksum=None):
    """Check if file needs to be backed up based on state and Google Drive metadata"""
    state = get_file_state(file_id)
    if not state:
        return True, "new file"  # No previous backup
    
    # Primary check: Google Drive MD5 checksum (if available)
    if drive_md5_checksum and state.get('drive_md5_checksum'):
        if state.get('drive_md5_checksum') != drive_md5_checksum:
            return True, "MD5 checksum changed"
    
    # Secondary check: modified time
    if modified_time and state.get('modified_time'):
        if modified_time > state['modified_time']:
            return True, "modified time newer"
    
    # Final fallback: our calculated hash (requires download)
    if file_hash and state.get('file_hash'):
        if state.get('file_hash') != file_hash:
            return True, "content hash changed"
        else:
            return False, f"content hash unchanged ({file_hash[:8]}...)"
    
    return False, "no changes detected"

def should_download_file(file_id, modified_time, drive_md5_checksum=None):
    """Check if file needs to be downloaded based on metadata only"""
    state = get_file_state(file_id)
    if not state:
        return True, "new file"  # No previous backup, need to download
    
    # If we have Google Drive MD5 checksum, use it for comparison
    if drive_md5_checksum and state.get('drive_md5_checksum'):
        if state.get('drive_md5_checksum') != drive_md5_checksum:
            return True, "MD5 checksum changed"
        else:
            return False, f"MD5 checksum unchanged ({drive_md5_checksum[:8]}...)"
    
    # Fallback to modified time comparison
    if modified_time and state.get('modified_time'):
        if modified_time > state['modified_time']:
            return True, "modified time newer"
        else:
            return False, f"modified time unchanged ({modified_time})"
    
    # If we have no metadata to compare, we need to download
    return True, "no metadata available - downloading to verify"

def list_shared_drives(service):
    """List all shared drives accessible to the service account"""
    shared_drives = []
    page_token = None
    
    try:
        while True:
            results = service.drives().list(
                pageSize=100,
                pageToken=page_token,
                fields="nextPageToken, drives(id, name)"
            ).execute()
            
            drives = results.get('drives', [])
            shared_drives.extend(drives)
            
            page_token = results.get('nextPageToken')
            if not page_token:
                break
                
        logger.info(f"Found {len(shared_drives)} shared drives")
        return shared_drives
        
    except Exception as e:
        logger.error(f"Error listing shared drives: {e}")
        return []

def list_files_from_drive(service, drive_id=None, drive_name=None):
    """List files from a specific drive or My Drive with optimized field selection"""
    files = []
    page_token = None
    
    query = "trashed=false"
    # Optimized field selection for metadata-based filtering
    list_params = {
        'pageSize': 100,
        'fields': "nextPageToken, files(id, name, mimeType, size, modifiedTime, owners, parents, md5Checksum)",
        'q': query,
        'supportsAllDrives': True,
        'includeItemsFromAllDrives': True
    }
    
    if drive_id:
        list_params['driveId'] = drive_id
        list_params['corpora'] = 'drive'
        logger.info(f"Listing files from shared drive: {drive_name or drive_id}")
    else:
        list_params['corpora'] = 'user'
        logger.info("Listing files from My Drive")
    
    try:
        while True:
            list_params['pageToken'] = page_token
            results = service.files().list(**list_params).execute()
            
            batch_files = results.get('files', [])
            files.extend(batch_files)
            
            page_token = results.get('nextPageToken')
            if not page_token:
                break
                
        return files
        
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return []

def get_files_metadata_batch(service, file_ids, fields="id,name,mimeType,size,modifiedTime,md5Checksum"):
    """Get metadata for multiple files using batch API requests"""
    from googleapiclient.http import BatchHttpRequest
    
    # Google Drive API allows up to 100 requests per batch
    BATCH_SIZE = 100
    all_files_metadata = []
    
    for i in range(0, len(file_ids), BATCH_SIZE):
        batch_ids = file_ids[i:i + BATCH_SIZE]
        batch_metadata = []
        
        def callback(request_id, response, exception):
            if exception:
                logger.warning(f"Error getting metadata for file {request_id}: {exception}")
            else:
                batch_metadata.append(response)
        
        try:
            batch_request = BatchHttpRequest(callback=callback)
            
            for file_id in batch_ids:
                batch_request.add(
                    service.files().get(
                        fileId=file_id,
                        fields=fields,
                        supportsAllDrives=True
                    ),
                    request_id=file_id
                )
            
            batch_request.execute()
            all_files_metadata.extend(batch_metadata)
            
            # Small delay to prevent rate limiting
            time.sleep(RATE_LIMIT_DELAY)
            
        except Exception as e:
            logger.error(f"Error executing batch request: {e}")
    
    return all_files_metadata

def get_file_path(service, file_id, file_name):
    """Get the full path of a file including parent folders"""
    try:
        path_parts = []
        current_id = file_id
        visited = set()  # Prevent infinite loops
        
        # Build path from file to root (will be reversed)
        while current_id and current_id not in visited:
            visited.add(current_id)
            
            # Get file/folder metadata
            file_metadata = service.files().get(
                fileId=current_id,
                fields='id,name,parents',
                supportsAllDrives=True
            ).execute()
            
            # Add to path (skip the initial file name as we already have it)
            if current_id != file_id:
                path_parts.append(file_metadata.get('name', ''))
            
            # Get parent folder
            parents = file_metadata.get('parents', [])
            if parents:
                current_id = parents[0]
            else:
                current_id = None
        
        # Reverse to get path from root to file
        path_parts.reverse()
        
        # Build full path
        if path_parts:
            full_path = '/'.join(filter(None, path_parts)) + '/' + file_name
        else:
            full_path = file_name
            
        return full_path
        
    except Exception as e:
        logger.warning(f"Could not determine full path for {file_name}: {str(e)}")
        return file_name

def download_file_streaming(service, file_id, file_name, mime_type):
    """Download a file from Google Drive using streaming for large files"""
    try:
        logger.info(f"Downloading file: {file_name}")
        
        # Handle Google Workspace documents
        if mime_type.startswith('application/vnd.google-apps'):
            export_formats = {
                'application/vnd.google-apps.document': ('application/pdf', '.pdf'),
                'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
                'application/vnd.google-apps.presentation': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx'),
                'application/vnd.google-apps.drawing': ('application/pdf', '.pdf')
            }
            
            if mime_type in export_formats:
                export_mime_type, extension = export_formats[mime_type]
                file_name += extension
                request = service.files().export_media(fileId=file_id, mimeType=export_mime_type)
            else:
                logger.info(f"Skipping unsupported Google Workspace file type: {mime_type}")
                return None, None, None
        else:
            request = service.files().get_media(fileId=file_id)
        
        # Use streaming download for large files
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.debug(f"Download {int(status.progress() * 100)}% complete")
        
        file_content = fh.getvalue()
        file_hash = calculate_file_hash(file_content)
        
        logger.info(f"Successfully downloaded: {file_name} (size: {len(file_content)} bytes)")
        return file_content, file_name, file_hash
        
    except Exception as e:
        logger.error(f"Error downloading file {file_name}: {str(e)}")
        return None, None, None

def upload_to_s3_multipart(content, s3_key, metadata):
    """Upload content to S3 using multipart upload for large files"""
    try:
        file_size = len(content) if isinstance(content, bytes) else len(content.encode('utf-8'))
        
        # Use multipart upload for files > 100MB
        if file_size > LARGE_FILE_THRESHOLD:
            logger.info(f"Using multipart upload for large file: {s3_key} ({file_size} bytes)")
            
            # Initiate multipart upload
            response = s3_client.create_multipart_upload(
                Bucket=S3_BUCKET,
                Key=s3_key,
                ServerSideEncryption='aws:kms',
                Metadata=metadata
            )
            upload_id = response['UploadId']
            
            # Upload parts
            parts = []
            part_size = 10 * 1024 * 1024  # 10MB parts
            
            for i in range(0, file_size, part_size):
                part_number = (i // part_size) + 1
                part_data = content[i:i + part_size]
                
                response = s3_client.upload_part(
                    Bucket=S3_BUCKET,
                    Key=s3_key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=part_data
                )
                
                parts.append({
                    'PartNumber': part_number,
                    'ETag': response['ETag']
                })
            
            # Complete multipart upload
            s3_client.complete_multipart_upload(
                Bucket=S3_BUCKET,
                Key=s3_key,
                UploadId=upload_id,
                MultipartUpload={'Parts': parts}
            )
        else:
            # Regular upload for smaller files
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
        logger.error(f"Error uploading to S3: {str(e)}")
        return False

def process_single_file(file, owner_email, backup_date, drive_name=None):
    """Process a single file for backup with incremental support"""
    file_name = file['name']
    file_id = file['id']
    mime_type = file.get('mimeType', 'application/octet-stream')
    modified_time = file.get('modifiedTime', '')
    drive_md5_checksum = file.get('md5Checksum')
    
    try:
        # Skip folders
        if mime_type == 'application/vnd.google-apps.folder':
            return {'status': 'folder', 'bytes': 0, 'reason': 'folder'}
        
        logger.info(f"Processing: {file_name} (owner: {owner_email}, drive: {drive_name or 'My Drive'})")
        
        # Pre-download check using metadata only
        should_download, reason = should_download_file(file_id, modified_time, drive_md5_checksum)
        if not should_download:
            logger.info(f"Skipping {file_name} - {reason}")
            return {'status': 'skipped', 'bytes': 0, 'reason': reason}
        
        # Create thread-safe service instance
        service = get_google_drive_service()
        
        # Download file and get hash
        file_content, final_name, file_hash = download_file_streaming(service, file_id, file_name, mime_type)
        
        if not file_content or not final_name:
            return {'status': 'failed', 'bytes': 0, 'reason': 'download failed'}
        
        # Final check if file needs backup (with downloaded hash)
        should_backup, reason = should_backup_file(file_id, file_hash, modified_time, drive_md5_checksum)
        if not should_backup:
            logger.info(f"Skipping {file_name} - {reason} (post-download check)")
            return {'status': 'skipped', 'bytes': 0, 'reason': reason + ' (post-download)'}
        
        # If we got here, we need to upload
        logger.info(f"Uploading {file_name} - {reason}")
        
        # Get file path
        file_path = get_file_path(service, file_id, final_name)
        
        # Create S3 key with organization
        username = owner_email.split('@')[0] if '@' in owner_email else owner_email
        
        # Include drive name in path for shared drives
        if drive_name:
            s3_key = f"{username}/shared-drives/{drive_name}/{backup_date}/{file_path}"
        else:
            s3_key = f"{username}/{backup_date}/{file_path}"
        
        # Prepare metadata
        metadata = {
            'original-owner': owner_email,
            'backup-date': backup_date,
            'source-file-id': file_id,
            'mime-type': mime_type,
            'file-hash': file_hash[:32],  # Truncate for metadata limit
            'modified-time': modified_time
        }
        
        if drive_name:
            metadata['drive-name'] = drive_name
        
        # Upload to S3
        file_size = len(file_content) if isinstance(file_content, bytes) else len(file_content.encode('utf-8'))
        
        if upload_to_s3_multipart(file_content, s3_key, metadata):
            # Update state tracking with Google Drive metadata
            update_file_state(file_id, file_hash, modified_time, s3_key, file_size, drive_md5_checksum)
            logger.info(f"Successfully uploaded to S3: {s3_key}")
            return {'status': 'uploaded', 'bytes': file_size, 'reason': reason}
        else:
            return {'status': 'failed', 'bytes': 0, 'reason': 'S3 upload failed'}
        
    except Exception as e:
        logger.error(f"Error processing {file_name}: {str(e)}")
        return {'status': 'failed', 'bytes': 0, 'reason': f'exception: {str(e)}'}

def process_files_batch(files, owner_email, backup_date, drive_name=None):
    """Process a batch of files using thread pool"""
    stats = {
        'uploaded': 0,
        'skipped': 0,
        'failed': 0,
        'folders': 0,
        'total_bytes': 0,
        'skip_reasons': {},
        'upload_reasons': {}
    }
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all files for processing
        future_to_file = {
            executor.submit(
                process_single_file, 
                file, 
                owner_email, 
                backup_date,
                drive_name
            ): file for file in files
        }
        
        # Process completed futures
        for future in as_completed(future_to_file):
            file = future_to_file[future]
            try:
                result = future.result()
                status = result['status']
                bytes_processed = result['bytes']
                reason = result['reason']
                
                if status == 'uploaded':
                    stats['uploaded'] += 1
                    stats['total_bytes'] += bytes_processed
                    stats['upload_reasons'][reason] = stats['upload_reasons'].get(reason, 0) + 1
                elif status == 'skipped':
                    stats['skipped'] += 1
                    stats['skip_reasons'][reason] = stats['skip_reasons'].get(reason, 0) + 1
                elif status == 'failed':
                    stats['failed'] += 1
                elif status == 'folder':
                    stats['folders'] += 1
                    
            except Exception as e:
                logger.error(f"Failed to process file {file.get('name', 'unknown')}: {str(e)}")
                stats['failed'] += 1
            
            # Small delay to prevent rate limiting
            time.sleep(RATE_LIMIT_DELAY)
    
    return stats

def send_metrics(user_email, file_count, success_count, total_bytes, drive_name=None):
    """Send metrics to CloudWatch"""
    try:
        namespace = 'GDriveBackup'
        dimensions = [{'Name': 'UserEmail', 'Value': user_email}]
        
        if drive_name:
            dimensions.append({'Name': 'DriveName', 'Value': drive_name})
        
        cloudwatch.put_metric_data(
            Namespace=namespace,
            MetricData=[
                {
                    'MetricName': 'FilesProcessed',
                    'Value': file_count,
                    'Unit': 'Count',
                    'Dimensions': dimensions
                },
                {
                    'MetricName': 'FilesSuccess',
                    'Value': success_count,
                    'Unit': 'Count',
                    'Dimensions': dimensions
                },
                {
                    'MetricName': 'BytesBackedUp',
                    'Value': total_bytes,
                    'Unit': 'Bytes',
                    'Dimensions': dimensions
                }
            ]
        )
    except Exception as e:
        logger.error(f"Error sending metrics: {e}")

def lambda_handler(event, context):
    """Main Lambda handler with enterprise features"""
    try:
        logger.info("Starting Google Drive backup process (Enterprise Edition)...")
        logger.info(f"Configuration: MAX_WORKERS={MAX_WORKERS}, BATCH_SIZE={BATCH_SIZE}, "
                   f"ENABLE_SHARED_DRIVES={ENABLE_SHARED_DRIVES}")
        
        # Get backup date
        backup_date = datetime.now().strftime('%Y-%m-%d')
        
        # Get Google Drive service
        service = get_google_drive_service()
        
        # Initialize statistics
        overall_stats = {
            'users_processed': 0,
            'drives_processed': 0,
            'total_files': 0,
            'total_success': 0,
            'total_failed': 0,
            'total_bytes': 0,
            'total_skipped': 0,
            'summaries': {}
        }
        
        # Process My Drive files
        logger.info("Processing My Drive files...")
        my_drive_files = list_files_from_drive(service)
        
        if my_drive_files:
            # Group files by owner
            files_by_owner = {}
            for file in my_drive_files:
                owners = file.get('owners', [])
                owner_email = owners[0].get('emailAddress', 'unknown') if owners else 'shared'
                
                if owner_email not in files_by_owner:
                    files_by_owner[owner_email] = []
                files_by_owner[owner_email].append(file)
            
            # Process each owner's files
            for owner_email, files in files_by_owner.items():
                logger.info(f"Processing {len(files)} files for user: {owner_email}")
                
                # Process in batches
                owner_stats = {
                    'uploaded': 0,
                    'skipped': 0,
                    'failed': 0,
                    'folders': 0,
                    'total_bytes': 0,
                    'skip_reasons': {},
                    'upload_reasons': {}
                }
                
                for i in range(0, len(files), BATCH_SIZE):
                    batch = files[i:i + BATCH_SIZE]
                    batch_stats = process_files_batch(
                        batch, owner_email, backup_date
                    )
                    
                    # Merge batch stats into owner stats
                    owner_stats['uploaded'] += batch_stats['uploaded']
                    owner_stats['skipped'] += batch_stats['skipped']
                    owner_stats['failed'] += batch_stats['failed']
                    owner_stats['folders'] += batch_stats['folders']
                    owner_stats['total_bytes'] += batch_stats['total_bytes']
                    
                    # Merge reason counts
                    for reason, count in batch_stats['skip_reasons'].items():
                        owner_stats['skip_reasons'][reason] = owner_stats['skip_reasons'].get(reason, 0) + count
                    for reason, count in batch_stats['upload_reasons'].items():
                        owner_stats['upload_reasons'][reason] = owner_stats['upload_reasons'].get(reason, 0) + count
                
                # Update overall stats
                overall_stats['total_success'] += owner_stats['uploaded']
                overall_stats['total_failed'] += owner_stats['failed']
                overall_stats['total_bytes'] += owner_stats['total_bytes']
                overall_stats['total_skipped'] += owner_stats['skipped']
                
                overall_stats['total_files'] += len(files)
                overall_stats['users_processed'] += 1
                
                # Send metrics
                send_metrics(owner_email, len(files), 
                           owner_stats['uploaded'], 
                           owner_stats['total_bytes'])
                
                # Log detailed stats for this owner
                logger.info(f"User {owner_email} summary: {owner_stats['uploaded']} uploaded, "
                           f"{owner_stats['skipped']} skipped, {owner_stats['failed']} failed")
                
                # Log skip reasons if any
                if owner_stats['skip_reasons']:
                    for reason, count in owner_stats['skip_reasons'].items():
                        logger.info(f"  Skipped {count} files: {reason}")
                
                # Log upload reasons if any
                if owner_stats['upload_reasons']:
                    for reason, count in owner_stats['upload_reasons'].items():
                        logger.info(f"  Uploaded {count} files: {reason}")
        
        # Process Shared Drives if enabled
        if ENABLE_SHARED_DRIVES:
            logger.info("Processing Shared Drives...")
            shared_drives = list_shared_drives(service)
            
            for drive in shared_drives:
                drive_id = drive['id']
                drive_name = drive['name']
                logger.info(f"Processing shared drive: {drive_name}")
                
                drive_files = list_files_from_drive(service, drive_id, drive_name)
                
                if drive_files:
                    # For shared drives, use the drive name as the primary organizer
                    drive_stats = {
                        'uploaded': 0,
                        'skipped': 0,
                        'failed': 0,
                        'folders': 0,
                        'total_bytes': 0,
                        'skip_reasons': {},
                        'upload_reasons': {}
                    }
                    
                    # Process in batches
                    for i in range(0, len(drive_files), BATCH_SIZE):
                        batch = drive_files[i:i + BATCH_SIZE]
                        batch_stats = process_files_batch(
                            batch, 'shared-drive', backup_date, drive_name
                        )
                        
                        # Merge batch stats into drive stats
                        drive_stats['uploaded'] += batch_stats['uploaded']
                        drive_stats['skipped'] += batch_stats['skipped']
                        drive_stats['failed'] += batch_stats['failed']
                        drive_stats['folders'] += batch_stats['folders']
                        drive_stats['total_bytes'] += batch_stats['total_bytes']
                        
                        # Merge reason counts
                        for reason, count in batch_stats['skip_reasons'].items():
                            drive_stats['skip_reasons'][reason] = drive_stats['skip_reasons'].get(reason, 0) + count
                        for reason, count in batch_stats['upload_reasons'].items():
                            drive_stats['upload_reasons'][reason] = drive_stats['upload_reasons'].get(reason, 0) + count
                    
                    overall_stats['total_files'] += len(drive_files)
                    overall_stats['total_success'] += drive_stats['uploaded']
                    overall_stats['total_failed'] += drive_stats['failed']
                    overall_stats['total_bytes'] += drive_stats['total_bytes']
                    overall_stats['total_skipped'] += drive_stats['skipped']
                    overall_stats['drives_processed'] += 1
                    
                    overall_stats['summaries'][f"SharedDrive:{drive_name}"] = {
                        'files': len(drive_files),
                        'uploaded': drive_stats['uploaded'],
                        'skipped': drive_stats['skipped'],
                        'failed': drive_stats['failed'],
                        'bytes': drive_stats['total_bytes']
                    }
                    
                    # Send metrics
                    send_metrics('shared-drive', len(drive_files), 
                               drive_stats['uploaded'], drive_stats['total_bytes'], drive_name)
                    
                    # Log detailed stats for this drive
                    logger.info(f"Shared Drive {drive_name} summary: {drive_stats['uploaded']} uploaded, "
                               f"{drive_stats['skipped']} skipped, {drive_stats['failed']} failed")
                    
                    # Log skip reasons if any
                    if drive_stats['skip_reasons']:
                        for reason, count in drive_stats['skip_reasons'].items():
                            logger.info(f"  Skipped {count} files: {reason}")
                    
                    # Log upload reasons if any
                    if drive_stats['upload_reasons']:
                        for reason, count in drive_stats['upload_reasons'].items():
                            logger.info(f"  Uploaded {count} files: {reason}")
        
        # Enhanced final summary
        logger.info("=== BACKUP SUMMARY ===")
        logger.info(f"Total Files Processed: {overall_stats['total_files']}")
        logger.info(f"  ✅ Uploaded: {overall_stats['total_success']} files ({overall_stats['total_bytes']:,} bytes)")
        logger.info(f"  ⏭️  Skipped: {overall_stats['total_skipped']} files")
        logger.info(f"  ❌ Failed: {overall_stats['total_failed']} files")
        logger.info(f"Users: {overall_stats['users_processed']}, Shared Drives: {overall_stats['drives_processed']}")
        logger.info("======================")
        
        # Legacy format for compatibility
        logger.info(f"Backup completed. Users: {overall_stats['users_processed']}, "
                   f"Shared Drives: {overall_stats['drives_processed']}, "
                   f"Files: {overall_stats['total_success']}/{overall_stats['total_files']} "
                   f"(Skipped: {overall_stats['total_skipped']})")
        
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