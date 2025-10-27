"""
Mock storage manager for development mode.
Provides local file storage without requiring GCS credentials.
"""

import os
import uuid
import shutil
import tempfile
import logging
from typing import List, Dict, Any
from datetime import datetime
from typing import List, Optional, Dict, Any, BinaryIO

from shared.models import Job, JobFile, FileType

logger = logging.getLogger(__name__)

class MockStorageManager:
    """Mock storage manager for development without GCS dependency."""
    
    def __init__(self):
        """Initialize mock storage with local filesystem."""
        # Use a directory that's accessible to Docker in WSL2
        # /tmp is not shared with Docker Desktop in WSL2, use home directory instead
        self.base_dir = os.path.join(os.path.expanduser("~"), ".grinn_dev_storage")
        os.makedirs(self.base_dir, exist_ok=True)
        logger.info(f"Mock storage initialized at: {self.base_dir}")
        
    def upload_job_files(self, job: Job, files: List[Dict[str, Any]]) -> List[JobFile]:
        """Mock upload files for a job."""
        uploaded_files = []
        
        job_dir = os.path.join(self.base_dir, job.job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        for file_data in files:
            file_id = str(uuid.uuid4())
            filename = file_data['filename']
            content = file_data['content']
            
            # Save file locally
            file_path = os.path.join(job_dir, filename)
            
            # Handle base64 encoded content
            if isinstance(content, str) and content.startswith('data:'):
                # Remove data URL prefix
                content = content.split(',')[1]
                import base64
                content = base64.b64decode(content)
            
            with open(file_path, 'wb') as f:
                if isinstance(content, str):
                    f.write(content.encode())
                else:
                    f.write(content)
            
            # Create JobFile object
            job_file = JobFile(
                filename=filename,
                file_type=self._detect_file_type(filename),
                size_bytes=os.path.getsize(file_path),
                gcs_path=file_path,  # Use local path instead
                upload_timestamp=datetime.utcnow()
            )
            uploaded_files.append(job_file)
            
        logger.info(f"Mock uploaded {len(uploaded_files)} files for job {job.job_id}")
        return uploaded_files
    
    def delete_job_files(self, job_id: str) -> bool:
        """Mock delete all files for a job."""
        try:
            job_dir = os.path.join(self.base_dir, job_id)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir)
                logger.info(f"Mock deleted files for job {job_id}")
            return True
        except Exception as e:
            logger.error(f"Mock deletion failed for job {job_id}: {e}")
            return False

    def generate_signed_url(self, gcs_path: str, expiration_hours: int = 24) -> str:
        """Mock generate a signed URL for downloading."""
        # Convert GCS path to local path for mock
        local_path = gcs_path.replace('gs://', self.base_dir + '/')
        return f"file://{local_path}"
    
    def list_job_files(self, job_id: str, file_type: str = "input") -> List[Dict[str, Any]]:
        """Mock list files for a job."""
        job_dir = os.path.join(self.base_dir, job_id)
        if os.path.exists(job_dir):
            files = []
            for filename in os.listdir(job_dir):
                file_path = os.path.join(job_dir, filename)
                if os.path.isfile(file_path):
                    files.append({
                        'name': filename,
                        'size': os.path.getsize(file_path),
                        'path': file_path,
                        'type': self._detect_file_type(filename).value
                    })
            return files
        return []
    
    def _detect_file_type(self, filename: str) -> FileType:
        """Detect file type from filename."""
        ext = filename.lower().split('.')[-1]
        if ext in ['pdb']:
            return FileType.PDB
        elif ext in ['gro']:
            return FileType.GRO
        elif ext in ['xtc']:
            return FileType.XTC
        elif ext in ['trr']:
            return FileType.TRR
        elif ext in ['tpr']:
            return FileType.TPR
        elif ext in ['top']:
            return FileType.TOP
        elif ext in ['itp']:
            return FileType.ITP
        elif ext in ['rtp']:
            return FileType.RTP
        else:
            return FileType.PDB  # Default fallback
    def generate_signed_upload_url(self, job_id: str, filename: str, 
                                   content_type: str = 'application/octet-stream',
                                   expiration: int = 3600) -> Dict[str, str]:
        """
        Mock generate signed URL for direct upload.
        Returns local file path instead of URL for development.
        """
        # Create input subdirectory to match download_job_inputs expectations
        job_dir = os.path.join(self.base_dir, job_id, 'input')
        os.makedirs(job_dir, exist_ok=True)
        
        file_path = os.path.join(job_dir, filename)
        
        # For mock storage, we return a special marker that tells the frontend
        # to use a different upload mechanism (POST to backend instead of PUT to URL)
        return {
            'upload_url': f'mock://localhost/{job_id}/{filename}',
            'file_path': file_path,
            'expiration': expiration
        }
    
    def generate_multiple_signed_upload_urls(self, job_id: str, 
                                             files_info: List[Dict[str, str]],
                                             expiration_minutes: int = 60) -> List[Dict[str, str]]:
        """
        Mock generate multiple signed upload URLs.
        
        Args:
            job_id: Job identifier
            files_info: List of dicts with 'filename', 'content_type', and 'file_type'
            expiration_minutes: URL expiration in minutes
            
        Returns:
            List of dicts with 'filename', 'upload_url', 'file_path', 'file_type'
        """
        urls = []
        for file_info in files_info:
            filename = file_info['filename']
            content_type = file_info.get('content_type', 'application/octet-stream')
            
            # Convert minutes to seconds for internal consistency
            expiration_seconds = expiration_minutes * 60
            url_info = self.generate_signed_upload_url(
                job_id, filename, content_type, expiration_seconds
            )
            
            urls.append({
                'filename': filename,
                'upload_url': url_info['upload_url'],
                'file_path': url_info['file_path'],
                'file_type': file_info.get('file_type', self._detect_file_type(filename).value)
            })
        
        return urls
    
    def verify_file_uploaded(self, file_path: str) -> bool:
        """
        Mock verify that a file was successfully uploaded.
        Checks if file exists in local storage.
        """
        exists = os.path.exists(file_path)
        if exists:
            size = os.path.getsize(file_path)
            logger.info(f"Mock verified file exists: {file_path} ({size} bytes)")
        else:
            logger.warning(f"Mock verification failed: {file_path} not found")
        return exists
    
    def download_job_inputs(self, job_id: str, local_dir: str) -> Dict[str, str]:
        """
        Mock download all input files for a job to a local directory.
        """
        try:
            os.makedirs(local_dir, exist_ok=True)
            job_dir = os.path.join(self.base_dir, job_id, 'input')
            
            file_paths = {}
            
            if os.path.exists(job_dir):
                for filename in os.listdir(job_dir):
                    src_path = os.path.join(job_dir, filename)
                    if os.path.isfile(src_path):
                        dest_path = os.path.join(local_dir, filename)
                        shutil.copy2(src_path, dest_path)
                        file_paths[filename] = dest_path
                        logger.debug(f"Mock downloaded {filename} to {dest_path}")
            
            logger.info(f"Mock downloaded {len(file_paths)} input files for job {job_id}")
            return file_paths
            
        except Exception as e:
            logger.error(f"Mock download input files failed for job {job_id}: {e}")
            raise
    
    def upload_job_results(self, job_id: str, results_dir: str) -> str:
        """
        Mock upload job results directory to storage.
        For mock storage, if results_dir is already the correct output location,
        no copying is needed since Docker writes directly there.
        """
        try:
            job_output_dir = os.path.join(self.base_dir, job_id, 'output')
            os.makedirs(job_output_dir, exist_ok=True)
            
            # Resolve both paths to absolute paths for comparison
            results_dir_resolved = os.path.abspath(results_dir)
            job_output_dir_resolved = os.path.abspath(job_output_dir)
            
            # If results are already in the correct location, no need to copy
            if results_dir_resolved == job_output_dir_resolved:
                logger.info(f"Results already in correct location for job {job_id}: {job_output_dir}")
                gcs_prefix = f"jobs/{job_id}/output/"
                return gcs_prefix
            
            # Copy all files from results_dir to job output directory
            for root, dirs, files in os.walk(results_dir):
                for file in files:
                    src_path = os.path.join(root, file)
                    rel_path = os.path.relpath(src_path, results_dir)
                    dest_path = os.path.join(job_output_dir, rel_path)
                    
                    # Create destination directory if needed
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.copy2(src_path, dest_path)
                    logger.debug(f"Mock uploaded result file {rel_path}")
            
            gcs_prefix = f"jobs/{job_id}/output/"
            logger.info(f"Mock uploaded results for job {job_id} to {gcs_prefix}")
            return gcs_prefix
            
        except Exception as e:
            logger.error(f"Mock upload results failed for job {job_id}: {e}")
            raise
    
    def download_job_results(self, job_id: str, local_dir: str) -> Dict[str, str]:
        """
        Mock download job results to a local directory.
        """
        try:
            os.makedirs(local_dir, exist_ok=True)
            job_output_dir = os.path.join(self.base_dir, job_id, 'output')
            
            file_paths = {}
            
            if os.path.exists(job_output_dir):
                for root, dirs, files in os.walk(job_output_dir):
                    for file in files:
                        src_path = os.path.join(root, file)
                        rel_path = os.path.relpath(src_path, job_output_dir)
                        dest_path = os.path.join(local_dir, rel_path)
                        
                        # Create destination directory if needed
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        shutil.copy2(src_path, dest_path)
                        file_paths[rel_path] = dest_path
                        logger.debug(f"Mock downloaded result file {rel_path}")
            
            logger.info(f"Mock downloaded {len(file_paths)} result files for job {job_id}")
            return file_paths
            
        except Exception as e:
            logger.error(f"Mock download results failed for job {job_id}: {e}")
            raise
    
    def check_bucket_access(self) -> bool:
        """
        Mock check bucket access - always returns True for local storage.
        """
        return True
