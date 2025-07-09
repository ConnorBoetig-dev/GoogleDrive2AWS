"""
AWS Lambda function for Gmail backup to S3 using Service Account
Backs up emails and attachments from Gmail to S3 with DynamoDB state tracking
"""

import json
import boto3
import os
import logging
import base64
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')

# Environment variables
S3_BUCKET = os.environ['S3_BUCKET']
SECRET_NAME = os.environ['SECRET_NAME']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
MAX_MESSAGES_PER_BATCH = int(os.environ.get('MAX_MESSAGES_PER_BATCH', '50'))
RATE_LIMIT_DELAY = float(os.environ.get('RATE_LIMIT_DELAY', '0.1'))
TARGET_EMAIL = os.environ.get('TARGET_EMAIL', 'me')  # Email to backup or 'me'

# DynamoDB table
state_table = dynamodb.Table(DYNAMODB_TABLE)

# Global credentials cache
_cached_credentials = None


def get_gmail_credentials():
    """Get Gmail credentials from Secrets Manager (cached)"""
    global _cached_credentials
    
    if _cached_credentials is None:
        try:
            logger.info("Getting Gmail credentials from Secrets Manager...")
            response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
            credentials_json = json.loads(response['SecretString'])
            
            _cached_credentials = service_account.Credentials.from_service_account_info(
                credentials_json,
                scopes=[
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/gmail.metadata'
                ]
            )
            
            # If using domain-wide delegation, delegate to target user
            if TARGET_EMAIL != 'me':
                _cached_credentials = _cached_credentials.with_subject(TARGET_EMAIL)
            
            logger.info("Gmail credentials cached successfully")
            
        except Exception as e:
            logger.error(f"Error getting Gmail credentials: {str(e)}")
            raise
    
    return _cached_credentials


def get_gmail_service() -> Any:
    """Initialize Gmail API service using service account credentials"""
    try:
        credentials = get_gmail_credentials()
        service = build('gmail', 'v1', credentials=credentials, cache_discovery=False)
        logger.info("Gmail service initialized successfully")
        return service
        
    except Exception as e:
        logger.error(f"Error creating Gmail service: {str(e)}")
        raise


def get_backup_state(message_id: str) -> Optional[Dict]:
    """Check if a message has already been backed up"""
    try:
        response = state_table.get_item(Key={'messageId': message_id})
        return response.get('Item')
    except Exception as e:
        logger.warning(f"Error checking backup state for {message_id}: {e}")
        return None


def update_backup_state(message_id: str, status: str = 'completed') -> None:
    """Update backup state in DynamoDB"""
    try:
        state_table.put_item(
            Item={
                'messageId': message_id,
                'backupStatus': status,
                'backupTimestamp': datetime.utcnow().isoformat(),
                'ttl': int((datetime.utcnow().timestamp() + 90 * 24 * 3600))  # 90 day TTL
            }
        )
        logger.debug(f"Updated backup state for {message_id}")
    except Exception as e:
        logger.error(f"Error updating backup state for {message_id}: {e}")


def fetch_messages(service: Any, query: str = 'label:INBOX', 
                  max_results: int = MAX_MESSAGES_PER_BATCH) -> List[Dict]:
    """Fetch message IDs from Gmail with pagination"""
    messages = []
    page_token = None
    user_id = TARGET_EMAIL if TARGET_EMAIL != 'me' else 'me'
    
    try:
        while len(messages) < max_results:
            batch_size = min(100, max_results - len(messages))
            
            results = service.users().messages().list(
                userId=user_id,
                q=query,
                pageToken=page_token,
                maxResults=batch_size
            ).execute()
            
            page_messages = results.get('messages', [])
            messages.extend(page_messages)
            
            page_token = results.get('nextPageToken')
            if not page_token or len(messages) >= max_results:
                break
                
            time.sleep(RATE_LIMIT_DELAY)
            
        logger.info(f"Fetched {len(messages)} message IDs")
        return messages[:max_results]
        
    except HttpError as e:
        logger.error(f"Error fetching messages: {e}")
        return messages


def get_message_details(service: Any, message_id: str) -> Optional[Dict]:
    """Get full message details including attachments"""
    max_retries = 3
    user_id = TARGET_EMAIL if TARGET_EMAIL != 'me' else 'me'
    
    for attempt in range(max_retries):
        try:
            message = service.users().messages().get(
                userId=user_id,
                id=message_id,
                format='full'
            ).execute()
            
            return message
            
        except HttpError as e:
            if e.resp.status == 429:  # Rate limit
                wait_time = (2 ** attempt) * 2
                logger.warning(f"Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Error fetching message {message_id}: {e}")
                return None
                
    return None


def extract_date_from_headers(headers: List[Dict]) -> datetime:
    """Extract date from email headers"""
    from email.utils import parsedate_to_datetime
    
    for header in headers:
        if header['name'].lower() == 'date':
            try:
                date_str = header['value']
                return parsedate_to_datetime(date_str)
            except Exception as e:
                logger.warning(f"Error parsing date '{date_str}': {e}")
                pass
    
    return datetime.utcnow()


def get_email_address(headers: List[Dict], header_name: str = 'From') -> str:
    """Extract email address from headers"""
    import re
    
    for header in headers:
        if header['name'].lower() == header_name.lower():
            email_value = header['value']
            
            # Extract email from "Name <email@domain.com>" format
            email_match = re.search(r'<([^>]+)>', email_value)
            if email_match:
                return email_match.group(1)
            
            # If no angle brackets, check if it's just an email
            if '@' in email_value:
                return email_value.split()[0]
            
            return email_value
    
    return 'unknown'


def build_eml_content(message: Dict) -> bytes:
    """Build .eml file content from Gmail message"""
    try:
        # Get the raw message if available
        if 'raw' in message:
            return base64.urlsafe_b64decode(message['raw'])
        
        # Otherwise build from payload
        payload = message['payload']
        headers = payload.get('headers', [])
        
        # Create email message
        msg = MIMEMultipart()
        
        # Add headers
        for header in headers:
            name = header['name']
            value = header['value']
            if name.lower() not in ['content-type', 'mime-version']:
                msg[name] = value
        
        # Process body
        body_content = extract_body(payload)
        if body_content:
            msg.attach(MIMEText(body_content, 'plain', 'utf-8'))
        
        return msg.as_bytes()
        
    except Exception as e:
        logger.error(f"Error building EML content: {e}")
        error_msg = f"Subject: Error processing email\nDate: {datetime.utcnow().isoformat()}\n\nError building EML content: {str(e)}"
        return error_msg.encode('utf-8')


def extract_body(payload: Dict) -> str:
    """Extract email body from payload"""
    body = ""
    
    def extract_text_from_part(part):
        if part.get('mimeType') == 'text/plain':
            data = part.get('body', {}).get('data', '')
            if data:
                try:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                except Exception as e:
                    logger.warning(f"Error decoding body part: {e}")
                    return ""
        return ""
    
    if 'parts' in payload:
        for part in payload['parts']:
            text = extract_text_from_part(part)
            if text:
                body += text
            
            if 'parts' in part:
                for subpart in part['parts']:
                    text = extract_text_from_part(subpart)
                    if text:
                        body += text
    else:
        body = extract_text_from_part(payload)
    
    return body


def process_attachments(service: Any, message_id: str, message: Dict) -> List[Tuple[str, bytes]]:
    """Extract attachments from message"""
    attachments = []
    user_id = TARGET_EMAIL if TARGET_EMAIL != 'me' else 'me'
    
    def process_parts(parts):
        for part in parts:
            filename = part.get('filename')
            
            if filename:
                attachment_id = part.get('body', {}).get('attachmentId')
                
                if attachment_id:
                    try:
                        att = service.users().messages().attachments().get(
                            userId=user_id,
                            messageId=message_id,
                            id=attachment_id
                        ).execute()
                        
                        data = base64.urlsafe_b64decode(att['data'])
                        attachments.append((filename, data))
                        
                        logger.info(f"Extracted attachment: {filename} ({len(data)} bytes)")
                        
                    except Exception as e:
                        logger.error(f"Error fetching attachment {filename}: {e}")
            
            if 'parts' in part:
                process_parts(part['parts'])
    
    payload = message.get('payload', {})
    if 'parts' in payload:
        process_parts(payload['parts'])
    
    return attachments


def upload_to_s3(key: str, content: bytes, metadata: Dict[str, str] = None) -> bool:
    """Upload content to S3 with retry logic"""
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            put_args = {
                'Bucket': S3_BUCKET,
                'Key': key,
                'Body': content,
                'ServerSideEncryption': 'AES256'
            }
            
            if metadata:
                clean_metadata = {}
                for k, v in metadata.items():
                    clean_key = k.replace('-', '_').lower()
                    clean_metadata[clean_key] = str(v)[:1024]
                put_args['Metadata'] = clean_metadata
            
            s3_client.put_object(**put_args)
            logger.debug(f"Uploaded to S3: {key}")
            return True
            
        except ClientError as e:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt)
                logger.warning(f"S3 upload failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed to upload {key} after {max_retries} attempts: {e}")
                return False
    
    return False


def process_message(message_id: str) -> bool:
    """Process a single message - download and save email + attachments"""
    try:
        # Check if already backed up
        state = get_backup_state(message_id)
        if state and state.get('backupStatus') == 'completed':
            logger.debug(f"Message {message_id} already backed up, skipping")
            return True
        
        # Create service instance
        service = get_gmail_service()
        
        # Get full message
        message = get_message_details(service, message_id)
        if not message:
            return False
        
        # Extract metadata
        headers = message['payload'].get('headers', [])
        date = extract_date_from_headers(headers)
        from_email = get_email_address(headers, 'From')
        to_email = get_email_address(headers, 'To')
        subject = get_email_address(headers, 'Subject')
        
        # Clean email for use in path
        user_folder = TARGET_EMAIL.split('@')[0] if '@' in TARGET_EMAIL else TARGET_EMAIL
        if user_folder == 'me':
            user_folder = from_email.split('@')[0] if '@' in from_email else 'unknown'
        
        # Build S3 paths
        date_path = f"{date.year:04d}/{date.month:02d}/{date.day:02d}"
        
        # Save email as .eml
        eml_key = f"{user_folder}/{date_path}/{message_id}.eml"
        eml_content = build_eml_content(message)
        
        metadata = {
            'message-id': message_id,
            'from': from_email,
            'to': to_email,
            'subject': subject[:100],
            'date': date.isoformat(),
            'backup-timestamp': datetime.utcnow().isoformat()
        }
        
        if not upload_to_s3(eml_key, eml_content, metadata):
            return False
        
        # Process attachments
        attachments = process_attachments(service, message_id, message)
        
        for filename, content in attachments:
            import re
            safe_filename = re.sub(r'[^\w\-_\.]', '_', filename)
            att_key = f"{user_folder}/attachments/{date_path}/{message_id}/{safe_filename}"
            
            att_metadata = {
                'message-id': message_id,
                'original-filename': filename,
                'size': str(len(content))
            }
            
            if not upload_to_s3(att_key, content, att_metadata):
                logger.warning(f"Failed to upload attachment {filename}")
        
        # Update state
        update_backup_state(message_id, 'completed')
        
        logger.info(f"Successfully backed up message {message_id} with {len(attachments)} attachments")
        return True
        
    except Exception as e:
        logger.error(f"Error processing message {message_id}: {e}")
        update_backup_state(message_id, 'failed')
        return False


def lambda_handler(event: Dict, context: Any) -> Dict:
    """Main Lambda handler"""
    try:
        logger.info("Starting Gmail backup process...")
        logger.info(f"Target email: {TARGET_EMAIL}")
        
        # Get parameters from event
        query = event.get('query', 'label:INBOX')
        max_messages = event.get('max_messages', MAX_MESSAGES_PER_BATCH)
        
        # Initialize Gmail service
        service = get_gmail_service()
        
        # Fetch messages
        messages = fetch_messages(service, query, max_messages)
        
        if not messages:
            logger.info("No messages to backup")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No messages found',
                    'processed': 0,
                    'success': 0,
                    'failed': 0
                })
            }
        
        # Process messages
        success_count = 0
        failed_count = 0
        
        for i, msg in enumerate(messages):
            message_id = msg['id']
            
            logger.info(f"Processing message {i+1}/{len(messages)}: {message_id}")
            
            if process_message(message_id):
                success_count += 1
            else:
                failed_count += 1
            
            time.sleep(RATE_LIMIT_DELAY)
        
        logger.info(f"Backup completed: {success_count} success, {failed_count} failed")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Gmail backup completed',
                'target_email': TARGET_EMAIL,
                'processed': len(messages),
                'success': success_count,
                'failed': failed_count
            })
        }
        
    except Exception as e:
        logger.error(f"Error in Gmail backup: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }