"""
Mock storage manager for development mode.
Provides local file storage without requiring GCS credentials.
"""

import os
import uuid
import shutil
import tempfile
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, BinaryIO

from shared.models import Job, JobFile, FileType

logger = logging.getLogger(__name__)

class MockStorageManager:
    """Mock storage manager for development without GCS dependency."""
    
    def __init__(self):
        """Initialize mock storage with local temporary directory."""
        self.base_dir = os.path.join(tempfile.gettempdir(), "grinn_dev_storage")
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
    
    def download_job_file(self, file_path: str) -> bytes:
        """Mock download a job file."""
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                return f.read()
        else:
            raise FileNotFoundError(f"File not found: {file_path}")
    
    def delete_job_files(self, job: Job) -> bool:
        """Mock delete all files for a job."""
        try:
            job_dir = os.path.join(self.base_dir, job.job_id)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir)
                logger.info(f"Mock deleted files for job {job.job_id}")
            return True
        except Exception as e:
            logger.error(f"Mock deletion failed for job {job.job_id}: {e}")
            return False
    
    def generate_download_url(self, file_path: str, expires_in: int = 3600) -> str:
        """Mock generate a download URL."""
        # Return a local file URL
        return f"file://{file_path}"
    
    def list_job_files(self, job_id: str) -> List[str]:
        """Mock list files for a job."""
        job_dir = os.path.join(self.base_dir, job_id)
        if os.path.exists(job_dir):
            return [f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))]
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
    
    def cleanup_old_files(self, days_old: int = 7) -> int:
        """Mock cleanup old files."""
        # In development, don't automatically clean up files
        return 0