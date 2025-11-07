"""Google Cloud Storage management."""

import os
import logging
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from datetime import datetime

from google.cloud import storage
from google.cloud.exceptions import NotFound, Conflict
from google.api_core import retry

logger = logging.getLogger(__name__)

class GCSManager:
    """Manage Google Cloud Storage operations."""
    
    def __init__(self, bucket_name: str, credentials_path: Optional[str] = None):
        """
        Initialize GCS manager.
        
        Args:
            bucket_name: Name of GCS bucket
            credentials_path: Path to service account credentials JSON
        """
        self.bucket_name = bucket_name
        
        # Set credentials if provided
        if credentials_path:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
        
        # Initialize client and bucket
        self.client = storage.Client()
        self.bucket = self._get_or_create_bucket()
    
    def _get_or_create_bucket(self) -> storage.Bucket:
        """Get existing bucket or create if doesn't exist."""
        try:
            bucket = self.client.get_bucket(self.bucket_name)
            logger.info(f"Using existing bucket: {self.bucket_name}")
            return bucket
        except NotFound:
            logger.info(f"Creating new bucket: {self.bucket_name}")
            bucket = self.client.create_bucket(self.bucket_name, location="US")
            
            # Set lifecycle rules for cost optimization
            bucket.add_lifecycle_rule(
                action={'type': 'SetStorageClass', 'storageClass': 'NEARLINE'},
                conditions={'age': 30}  # Move to Nearline after 30 days
            )
            bucket.add_lifecycle_rule(
                action={'type': 'SetStorageClass', 'storageClass': 'COLDLINE'},
                conditions={'age': 90}  # Move to Coldline after 90 days
            )
            bucket.patch()
            
            return bucket
    
    @retry.Retry(deadline=60.0)  # Retry for up to 60 seconds
    def upload_file(
        self,
        local_path: Path,
        gcs_path: str,
        metadata: Optional[Dict] = None,
        content_type: str = 'application/pdf'
    ) -> Tuple[str, str]:
        """
        Upload file to GCS with retry logic.
        
        Args:
            local_path: Path to local file
            gcs_path: Destination path in GCS
            metadata: Optional metadata to attach
            content_type: MIME type of file
            
        Returns:
            Tuple of (gcs_url, checksum)
            
        Raises:
            Exception: If upload fails after retries
        """
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        
        # Calculate checksum
        checksum = self._calculate_checksum(local_path)
        
        # Check if file already exists with same checksum
        blob = self.bucket.blob(gcs_path)
        if blob.exists():
            blob.reload()
            existing_checksum = blob.metadata.get('checksum') if blob.metadata else None
            if existing_checksum == checksum:
                logger.info(f"File already exists with same checksum: {gcs_path}")
                return (f"gs://{self.bucket_name}/{gcs_path}", checksum)
        
        # Prepare metadata
        if metadata is None:
            metadata = {}
        metadata.update({
            'checksum': checksum,
            'upload_time': datetime.now().isoformat(),
            'original_filename': local_path.name
        })
        
        # Upload file
        blob = self.bucket.blob(gcs_path)
        blob.metadata = metadata
        
        logger.info(f"Uploading {local_path.name} to {gcs_path}")
        
        with open(local_path, 'rb') as f:
            blob.upload_from_file(f, content_type=content_type)
        
        # Verify upload
        if not blob.exists():
            raise Exception(f"Upload verification failed for {gcs_path}")
        
        gcs_url = f"gs://{self.bucket_name}/{gcs_path}"
        logger.info(f"Successfully uploaded to {gcs_url}")
        
        return (gcs_url, checksum)
    
    def download_file(self, gcs_path: str, local_path: Path) -> Path:
        """
        Download file from GCS.
        
        Args:
            gcs_path: Path in GCS
            local_path: Local destination path
            
        Returns:
            Path to downloaded file
        """
        blob = self.bucket.blob(gcs_path)
        
        if not blob.exists():
            raise FileNotFoundError(f"GCS file not found: {gcs_path}")
        
        # Create parent directory if needed
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading {gcs_path} to {local_path}")
        blob.download_to_filename(str(local_path))
        
        return local_path
    
    def file_exists(self, gcs_path: str) -> bool:
        """
        Check if file exists in GCS.
        
        Args:
            gcs_path: Path in GCS
            
        Returns:
            True if exists, False otherwise
        """
        blob = self.bucket.blob(gcs_path)
        return blob.exists()
    
    def get_file_metadata(self, gcs_path: str) -> Optional[Dict]:
        """
        Get metadata for file in GCS.
        
        Args:
            gcs_path: Path in GCS
            
        Returns:
            Metadata dictionary or None if not found
        """
        blob = self.bucket.blob(gcs_path)
        
        if not blob.exists():
            return None
        
        blob.reload()
        
        return {
            'size': blob.size,
            'content_type': blob.content_type,
            'created': blob.time_created,
            'updated': blob.updated,
            'metadata': blob.metadata,
            'md5_hash': blob.md5_hash,
            'crc32c': blob.crc32c
        }
    
    def list_files(self, prefix: str = '', limit: Optional[int] = None) -> List[str]:
        """
        List files in bucket with optional prefix filter.
        
        Args:
            prefix: Path prefix to filter by
            limit: Maximum number of results
            
        Returns:
            List of file paths
        """
        blobs = self.bucket.list_blobs(prefix=prefix, max_results=limit)
        return [blob.name for blob in blobs]
    
    def delete_file(self, gcs_path: str) -> bool:
        """
        Delete file from GCS.
        
        Args:
            gcs_path: Path in GCS
            
        Returns:
            True if deleted, False if didn't exist
        """
        blob = self.bucket.blob(gcs_path)
        
        if blob.exists():
            blob.delete()
            logger.info(f"Deleted {gcs_path}")
            return True
        
        return False
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """
        Calculate SHA256 checksum of file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Hex string of checksum
        """
        sha256_hash = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
    
    def create_folder_structure(self):
        """Create the expected folder structure in GCS."""
        # In GCS, folders are virtual and created automatically when files are uploaded
        # But we can create placeholder files to establish the structure
        structure = [
            'documents/optimized-pdfs/deeds/',
            'documents/optimized-pdfs/deeds-of-trust/',
            'documents/optimized-pdfs/wills/',
            'documents/optimized-pdfs/chancery/',
            'documents/extracted-text/deeds/',
            'documents/extracted-text/deeds-of-trust/',
            'documents/extracted-text/wills/',
            'documents/extracted-text/chancery/',
            'indexes/master-index/',
            'indexes/search-indexes/'
        ]
        
        for path in structure:
            # Create a placeholder file to establish the folder
            blob = self.bucket.blob(f"{path}.placeholder")
            if not blob.exists():
                blob.upload_from_string('', content_type='text/plain')
                logger.debug(f"Created folder structure: {path}")
    
    def get_storage_statistics(self) -> Dict:
        """Get storage statistics for the bucket."""
        stats = {
            'total_files': 0,
            'total_size': 0,
            'by_type': {},
            'by_folder': {}
        }
        
        for blob in self.bucket.list_blobs():
            stats['total_files'] += 1
            stats['total_size'] += blob.size or 0
            
            # By type
            if blob.name.endswith('.pdf'):
                file_type = 'pdf'
            elif blob.name.endswith('.json'):
                file_type = 'json'
            else:
                file_type = 'other'
            
            stats['by_type'][file_type] = stats['by_type'].get(file_type, 0) + 1
            
            # By folder (first level)
            folder = blob.name.split('/')[0] if '/' in blob.name else 'root'
            stats['by_folder'][folder] = stats['by_folder'].get(folder, 0) + 1
        
        return stats