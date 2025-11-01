"""
Google Cloud Storage utilities for gRINN Web Service.
Handles file upload, download, and management for job processing.
"""

import os
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, BinaryIO
import base64
import tempfile

try:
    from google.cloud import storage
    from google.auth import default
    from google.oauth2 import service_account
    HAS_GCS = True
except ImportError:
    HAS_GCS = False
    storage = None

from shared.config import get_config
from shared.models import Job, JobFile

logger = logging.getLogger(__name__)
config = get_config()

class CloudStorageManager:
    """Manages Google Cloud Storage operations for gRINN jobs."""
    
    def __init__(self):
        if not HAS_GCS:
            raise ImportError("Google Cloud Storage library not installed. Install with: pip install google-cloud-storage")
        
        self.bucket_name = config.gcs_bucket_name
        self.project_id = config.gcs_project_id
        self.credentials_path = config.gcs_credentials_path
        
        # Initialize client
        self._client = None
        self._bucket = None
        
    @property
    def client(self):
        """Get or create Google Cloud Storage client."""
        if self._client is None:
            try:
                if self.credentials_path and os.path.exists(self.credentials_path):
                    credentials = service_account.Credentials.from_service_account_file(
                        self.credentials_path
                    )
                    self._client = storage.Client(
                        credentials=credentials,
                        project=self.project_id
                    )
                else:
                    # Use default credentials (environment variables, service account, etc.)
                    self._client = storage.Client(project=self.project_id)
                
                logger.info("Successfully initialized Google Cloud Storage client")
                
            except Exception as e:
                logger.error(f"Failed to initialize GCS client: {e}")
                raise
        
        return self._client
    
    @property 
    def bucket(self):
        """Get or create bucket reference."""
        if self._bucket is None:
            try:
                self._bucket = self.client.bucket(self.bucket_name)
                # Test bucket access
                self._bucket.exists()
                logger.info(f"Successfully connected to bucket: {self.bucket_name}")
            except Exception as e:
                logger.error(f"Failed to access bucket {self.bucket_name}: {e}")
                raise
        
        return self._bucket
    
    def _get_job_prefix(self, job_id: str) -> str:
        """Get the GCS prefix for a job's files."""
        return f"jobs/{job_id}/"
    
    def _get_input_prefix(self, job_id: str) -> str:
        """Get the GCS prefix for job input files."""
        return f"{self._get_job_prefix(job_id)}input/"
    
    def _get_output_prefix(self, job_id: str) -> str:
        """Get the GCS prefix for job output files."""
        return f"{self._get_job_prefix(job_id)}output/"
    
    def upload_file_content(self, job_id: str, filename: str, content_base64: str, 
                           content_type: str = "application/octet-stream") -> str:
        """
        Upload file content to GCS.
        
        Args:
            job_id: Unique job identifier
            filename: Original filename
            content_base64: Base64 encoded file content
            content_type: MIME type of the file
            
        Returns:
            GCS path of uploaded file
        """
        try:
            # Decode base64 content
            file_content = base64.b64decode(content_base64)
            
            # Create GCS object path
            gcs_path = f"{self._get_input_prefix(job_id)}{filename}"
            
            # Upload to GCS
            blob = self.bucket.blob(gcs_path)
            blob.upload_from_string(
                file_content,
                content_type=content_type
            )
            
            # Set metadata
            blob.metadata = {
                'job_id': job_id,
                'original_filename': filename,
                'upload_timestamp': datetime.utcnow().isoformat(),
                'file_size': str(len(file_content))
            }
            blob.patch()
            
            logger.info(f"Uploaded file {filename} for job {job_id} to {gcs_path}")
            return gcs_path
            
        except Exception as e:
            logger.error(f"Failed to upload file {filename} for job {job_id}: {e}")
            raise
    
    def upload_job_files(self, job: Job, uploaded_files: List[Dict[str, Any]]) -> bool:
        """
        Upload all files for a job.
        
        Args:
            job: Job object to update with GCS paths
            uploaded_files: List of file data with content
            
        Returns:
            True if all files uploaded successfully
        """
        try:
            for i, file_data in enumerate(uploaded_files):
                filename = file_data['filename']
                content = file_data['content']
                
                # Upload file
                gcs_path = self.upload_file_content(
                    job.job_id,
                    filename,
                    content
                )
                
                # Update job file with GCS path
                if i < len(job.input_files):
                    job.input_files[i].gcs_path = gcs_path
            
            logger.info(f"Successfully uploaded {len(uploaded_files)} files for job {job.job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload files for job {job.job_id}: {e}")
            return False
    
    def download_job_inputs(self, job_id: str, local_dir: str) -> Dict[str, str]:
        """
        Download all input files for a job to a local directory.
        
        Args:
            job_id: Job identifier
            local_dir: Local directory to download files to
            
        Returns:
            Dictionary mapping original filename to local file path
        """
        try:
            os.makedirs(local_dir, exist_ok=True)
            
            # List all input files for the job
            input_prefix = self._get_input_prefix(job_id)
            blobs = self.bucket.list_blobs(prefix=input_prefix)
            
            file_paths = {}
            
            for blob in blobs:
                # Extract original filename from path
                filename = blob.name.replace(input_prefix, "")
                if not filename:  # Skip directory-only entries
                    continue
                
                # Download file
                local_path = os.path.join(local_dir, filename)
                
                # Create parent directory if filename contains subdirectories
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                
                blob.download_to_filename(local_path)
                
                file_paths[filename] = local_path
                logger.debug(f"Downloaded {filename} to {local_path}")
            
            logger.info(f"Downloaded {len(file_paths)} input files for job {job_id}")
            return file_paths
            
        except Exception as e:
            logger.error(f"Failed to download input files for job {job_id}: {e}")
            raise
    
    def upload_job_results(self, job_id: str, results_dir: str) -> str:
        """
        Upload job results directory to GCS.
        
        Args:
            job_id: Job identifier
            results_dir: Local directory containing results
            
        Returns:
            GCS prefix for the uploaded results
        """
        try:
            output_prefix = self._get_output_prefix(job_id)
            
            # Upload all files in results directory
            for root, dirs, files in os.walk(results_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    
                    # Calculate relative path within results directory
                    rel_path = os.path.relpath(local_path, results_dir)
                    
                    # Create GCS path
                    gcs_path = f"{output_prefix}{rel_path}"
                    
                    # Upload file
                    blob = self.bucket.blob(gcs_path)
                    blob.upload_from_filename(local_path)
                    
                    # Set metadata
                    blob.metadata = {
                        'job_id': job_id,
                        'result_file': 'true',
                        'upload_timestamp': datetime.utcnow().isoformat()
                    }
                    blob.patch()
                    
                    logger.debug(f"Uploaded result file {rel_path} to {gcs_path}")
            
            logger.info(f"Successfully uploaded results for job {job_id} to {output_prefix}")
            return output_prefix
            
        except Exception as e:
            logger.error(f"Failed to upload results for job {job_id}: {e}")
            raise
    
    def download_job_results(self, job_id: str, local_dir: str) -> Dict[str, str]:
        """
        Download job results to a local directory.
        
        Args:
            job_id: Job identifier
            local_dir: Local directory to download results to
            
        Returns:
            Dictionary mapping result filename to local path
        """
        try:
            os.makedirs(local_dir, exist_ok=True)
            
            # List all result files for the job
            output_prefix = self._get_output_prefix(job_id)
            blobs = self.bucket.list_blobs(prefix=output_prefix)
            
            file_paths = {}
            
            for blob in blobs:
                # Extract relative filename from path
                rel_filename = blob.name.replace(output_prefix, "")
                if not rel_filename:  # Skip directory-only entries
                    continue
                
                # Create local path preserving directory structure
                local_path = os.path.join(local_dir, rel_filename)
                
                # Create directory if needed
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                
                # Download file
                blob.download_to_filename(local_path)
                
                file_paths[rel_filename] = local_path
                logger.debug(f"Downloaded result {rel_filename} to {local_path}")
            
            logger.info(f"Downloaded {len(file_paths)} result files for job {job_id}")
            return file_paths
            
        except Exception as e:
            logger.error(f"Failed to download results for job {job_id}: {e}")
            raise
    
    def generate_signed_url(self, gcs_path: str, expiration_hours: int = 24) -> str:
        """
        Generate a signed URL for accessing a file in GCS.
        
        Args:
            gcs_path: Path to file in GCS
            expiration_hours: Hours until URL expires
            
        Returns:
            Signed URL for file access
        """
        try:
            blob = self.bucket.blob(gcs_path)
            
            # Generate signed URL
            url = blob.generate_signed_url(
                expiration=datetime.utcnow() + timedelta(hours=expiration_hours),
                method='GET'
            )
            
            logger.debug(f"Generated signed URL for {gcs_path}")
            return url
            
        except Exception as e:
            logger.error(f"Failed to generate signed URL for {gcs_path}: {e}")
            raise
    
    def list_job_files(self, job_id: str, file_type: str = "input") -> List[Dict[str, Any]]:
        """
        List files for a job.
        
        Args:
            job_id: Job identifier
            file_type: "input" or "output"
            
        Returns:
            List of file information dictionaries
        """
        try:
            if file_type == "input":
                prefix = self._get_input_prefix(job_id)
            elif file_type == "output":
                prefix = self._get_output_prefix(job_id)
            else:
                raise ValueError(f"Invalid file_type: {file_type}")
            
            blobs = self.bucket.list_blobs(prefix=prefix)
            
            files = []
            for blob in blobs:
                filename = blob.name.replace(prefix, "")
                if not filename:  # Skip directory-only entries
                    continue
                
                files.append({
                    'filename': filename,
                    'gcs_path': blob.name,
                    'size_bytes': blob.size,
                    'created': blob.time_created.isoformat() if blob.time_created else None,
                    'updated': blob.updated.isoformat() if blob.updated else None,
                    'content_type': blob.content_type,
                    'metadata': blob.metadata or {}
                })
            
            logger.debug(f"Listed {len(files)} {file_type} files for job {job_id}")
            return files
            
        except Exception as e:
            logger.error(f"Failed to list {file_type} files for job {job_id}: {e}")
            raise
    
    def delete_job_files(self, job_id: str) -> bool:
        """
        Delete all files for a job (both input and output).
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if deletion successful
        """
        try:
            job_prefix = self._get_job_prefix(job_id)
            
            # List all files for the job
            blobs = self.bucket.list_blobs(prefix=job_prefix)
            
            # Delete all blobs
            for blob in blobs:
                blob.delete()
                logger.debug(f"Deleted {blob.name}")
            
            logger.info(f"Successfully deleted all files for job {job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete files for job {job_id}: {e}")
            return False
    
    def check_bucket_access(self) -> bool:
        """
        Check if the bucket is accessible.
        
        Returns:
            True if bucket is accessible
        """
        try:
            self.bucket.exists()
            return True
        except Exception as e:
            logger.error(f"Bucket access check failed: {e}")
            return False
    
    def generate_signed_upload_url(self, job_id: str, filename: str, 
                                   content_type: str = "application/octet-stream",
                                   expiration_minutes: int = 60) -> Dict[str, str]:
        """
        Generate a signed URL for direct file upload to GCS.
        
        Args:
            job_id: Unique job identifier
            filename: Name of the file to be uploaded
            content_type: MIME type of the file
            expiration_minutes: How long the URL should be valid (default: 60 minutes)
            
        Returns:
            Dictionary with 'upload_url', 'file_path', and 'expires_at'
        """
        try:
            # Create GCS object path
            gcs_path = f"{self._get_input_prefix(job_id)}{filename}"
            
            # Get blob reference
            blob = self.bucket.blob(gcs_path)
            
            # Generate signed URL for PUT operation
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=expiration_minutes),
                method="PUT",
                content_type=content_type,
                # Add custom metadata headers
                headers={
                    'x-goog-meta-job-id': job_id,
                    'x-goog-meta-original-filename': filename,
                    'x-goog-meta-upload-timestamp': datetime.utcnow().isoformat()
                }
            )
            
            expires_at = datetime.utcnow() + timedelta(minutes=expiration_minutes)
            
            logger.info(f"Generated signed upload URL for {filename} (job {job_id}), expires at {expires_at}")
            
            return {
                'upload_url': signed_url,
                'file_path': gcs_path,
                'expires_at': expires_at.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to generate signed URL for {filename} (job {job_id}): {e}")
            raise
    
    def generate_multiple_signed_upload_urls(self, job_id: str, 
                                            files_info: List[Dict[str, str]],
                                            expiration_minutes: int = 60) -> List[Dict[str, str]]:
        """
        Generate signed URLs for multiple files.
        
        Args:
            job_id: Unique job identifier
            files_info: List of dicts with 'filename', 'content_type', and 'file_type'
            expiration_minutes: How long the URLs should be valid
            
        Returns:
            List of dictionaries with upload information for each file
        """
        try:
            upload_urls = []
            
            for file_info in files_info:
                url_data = self.generate_signed_upload_url(
                    job_id=job_id,
                    filename=file_info['filename'],
                    content_type=file_info.get('content_type', 'application/octet-stream'),
                    expiration_minutes=expiration_minutes
                )
                
                url_data['file_type'] = file_info.get('file_type', 'unknown')
                url_data['filename'] = file_info['filename']
                upload_urls.append(url_data)
            
            logger.info(f"Generated {len(upload_urls)} signed upload URLs for job {job_id}")
            return upload_urls
            
        except Exception as e:
            logger.error(f"Failed to generate multiple signed URLs for job {job_id}: {e}")
            raise
    
    def verify_file_uploaded(self, gcs_path: str) -> bool:
        """
        Verify that a file was successfully uploaded to GCS.
        
        Args:
            gcs_path: GCS path to check
            
        Returns:
            True if file exists
        """
        try:
            blob = self.bucket.blob(gcs_path)
            return blob.exists()
        except Exception as e:
            logger.error(f"Failed to verify file at {gcs_path}: {e}")
            return False


# Global storage manager instance
_storage_manager = None

def validate_storage_manager_interface(storage_manager):
    """
    Validate that storage manager has all required methods with correct signatures.
    This helps catch interface mismatches early in development.
    """
    required_methods = [
        'generate_multiple_signed_upload_urls',
        'verify_file_uploaded',
        'download_job_inputs',
        'upload_job_results',
        'download_job_results',
        'delete_job_files',
        'list_job_files',
        'generate_signed_url',
        'check_bucket_access'
    ]
    
    missing_methods = []
    for method_name in required_methods:
        if not hasattr(storage_manager, method_name):
            missing_methods.append(method_name)
        elif not callable(getattr(storage_manager, method_name)):
            missing_methods.append(f"{method_name} (not callable)")
    
    if missing_methods:
        raise AttributeError(f"Storage manager missing required methods: {missing_methods}")
    
    logger.info("Storage manager interface validation passed")

def get_storage_manager():
    """Get the global storage manager instance (Cloud or Mock for development)."""
    global _storage_manager
    if _storage_manager is None:
        # Use mock storage in development mode
        is_development = (os.getenv('FLASK_ENV') == 'development' or 
                         os.getenv('DASH_ENV') == 'development' or
                         os.getenv('DEVELOPMENT_MODE', 'false').lower() == 'true')
        
        if is_development:
            from shared.mock_storage import MockStorageManager
            _storage_manager = MockStorageManager()
            logger.info("Using MockStorageManager for development")
        else:
            _storage_manager = CloudStorageManager()
            logger.info("Using CloudStorageManager for production")
            
        # Validate interface compatibility
        try:
            validate_storage_manager_interface(_storage_manager)
        except AttributeError as e:
            logger.error(f"Storage manager interface validation failed: {e}")
            raise
            
    return _storage_manager