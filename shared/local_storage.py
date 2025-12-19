"""
Local Storage Manager for gRINN Web Service.
Handles file storage operations using local filesystem (with optional NFS for multi-worker setups).
"""

import os
import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import hashlib
import json

logger = logging.getLogger(__name__)


class LocalStorageManager:
    """
    Manages local filesystem storage operations for gRINN jobs.
    
    Storage structure:
        {storage_path}/
        └── jobs/
            └── {job_id}/
                ├── input/     # Input files uploaded by user
                ├── output/    # Results from gRINN processing
                └── metadata.json  # Job file metadata
    
    For multi-worker deployments, storage_path should be an NFS mount point
    accessible by all workers.
    """
    
    def __init__(self, storage_path: str = "/data/grinn-jobs"):
        """
        Initialize the local storage manager.
        
        Args:
            storage_path: Base path for job storage. Should be an NFS mount 
                         for multi-worker deployments.
        """
        self.storage_path = Path(storage_path)
        self.jobs_path = self.storage_path / "jobs"
        
        # Create base directories
        self._ensure_directories()
        
        logger.info(f"LocalStorageManager initialized with storage path: {self.storage_path}")
    
    def _ensure_directories(self):
        """Ensure base directory structure exists."""
        self.jobs_path.mkdir(parents=True, exist_ok=True)
    
    def _get_job_path(self, job_id: str) -> Path:
        """Get the base path for a job."""
        return self.jobs_path / job_id
    
    def _get_input_path(self, job_id: str) -> Path:
        """Get the input directory path for a job."""
        return self._get_job_path(job_id) / "input"
    
    def _get_output_path(self, job_id: str) -> Path:
        """Get the output directory path for a job."""
        return self._get_job_path(job_id) / "output"
    
    def _get_metadata_path(self, job_id: str) -> Path:
        """Get the metadata file path for a job."""
        return self._get_job_path(job_id) / "metadata.json"
    
    def create_job_directories(self, job_id: str) -> Dict[str, str]:
        """
        Create input and output directories for a new job.
        
        Args:
            job_id: Unique job identifier
            
        Returns:
            Dict with 'input' and 'output' directory paths
        """
        input_path = self._get_input_path(job_id)
        output_path = self._get_output_path(job_id)
        
        input_path.mkdir(parents=True, exist_ok=True)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize metadata
        metadata = {
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_files": [],
            "output_files": []
        }
        self._save_metadata(job_id, metadata)
        
        logger.info(f"Created job directories for {job_id}")
        
        return {
            "input": str(input_path),
            "output": str(output_path)
        }
    
    def _save_metadata(self, job_id: str, metadata: Dict[str, Any]):
        """Save job metadata to JSON file."""
        metadata_path = self._get_metadata_path(job_id)
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def _load_metadata(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Load job metadata from JSON file."""
        metadata_path = self._get_metadata_path(job_id)
        if metadata_path.exists():
            with open(metadata_path, 'r') as f:
                return json.load(f)
        return None
    
    def upload_file_content(
        self,
        job_id: str,
        filename: str,
        content: bytes,
        file_type: str = "input"
    ) -> str:
        """
        Save file content to job storage.
        
        Args:
            job_id: Job identifier
            filename: Name of the file
            content: File content as bytes
            file_type: Either 'input' or 'output'
            
        Returns:
            Full path to the saved file
        """
        if file_type == "input":
            target_dir = self._get_input_path(job_id)
        else:
            target_dir = self._get_output_path(job_id)
        
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename
        
        with open(file_path, 'wb') as f:
            f.write(content)
        
        # Update metadata
        metadata = self._load_metadata(job_id) or {
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_files": [],
            "output_files": []
        }
        
        file_info = {
            "filename": filename,
            "size": len(content),
            "checksum": hashlib.md5(content).hexdigest(),
            "uploaded_at": datetime.now(timezone.utc).isoformat()
        }
        
        if file_type == "input":
            # Remove existing entry for same filename if exists
            metadata["input_files"] = [
                f for f in metadata.get("input_files", []) 
                if f["filename"] != filename
            ]
            metadata["input_files"].append(file_info)
        else:
            metadata["output_files"] = [
                f for f in metadata.get("output_files", []) 
                if f["filename"] != filename
            ]
            metadata["output_files"].append(file_info)
        
        self._save_metadata(job_id, metadata)
        
        logger.debug(f"Saved {file_type} file {filename} for job {job_id}")
        return str(file_path)
    
    def get_upload_path(self, job_id: str, filename: str) -> str:
        """
        Get the path where a file should be uploaded.
        Used for direct file uploads without going through upload_file_content.
        
        Args:
            job_id: Job identifier
            filename: Name of the file
            
        Returns:
            Full path where the file should be saved
        """
        input_path = self._get_input_path(job_id)
        input_path.mkdir(parents=True, exist_ok=True)
        return str(input_path / filename)
    
    def download_job_inputs(self, job_id: str, target_dir: str) -> Dict[str, str]:
        """
        Copy all input files for a job to target directory.
        
        For local storage, if the input directory is already accessible (e.g., NFS),
        this returns paths to the original files. If target_dir differs from 
        the input directory, files are copied.
        
        Args:
            job_id: Job identifier
            target_dir: Directory to copy files to
            
        Returns:
            Dict mapping filename to full path
        """
        input_path = self._get_input_path(job_id)
        target_path = Path(target_dir)
        
        if not input_path.exists():
            logger.warning(f"Input directory does not exist for job {job_id}")
            return {}
        
        file_paths = {}
        
        for file_path in input_path.iterdir():
            if file_path.is_file():
                filename = file_path.name
                
                # If target is the same as input, just return the path
                if target_path == input_path:
                    file_paths[filename] = str(file_path)
                else:
                    # Copy to target directory
                    target_file = target_path / filename
                    shutil.copy2(file_path, target_file)
                    file_paths[filename] = str(target_file)
        
        logger.info(f"Retrieved {len(file_paths)} input files for job {job_id}")
        return file_paths
    
    def get_input_directory(self, job_id: str) -> str:
        """
        Get the input directory path for a job.
        Useful when workers can directly access the storage (e.g., NFS).
        
        Args:
            job_id: Job identifier
            
        Returns:
            Path to input directory
        """
        return str(self._get_input_path(job_id))
    
    def get_output_directory(self, job_id: str) -> str:
        """
        Get the output directory path for a job.
        Useful when workers can directly access the storage (e.g., NFS).
        
        Args:
            job_id: Job identifier
            
        Returns:
            Path to output directory
        """
        output_path = self._get_output_path(job_id)
        output_path.mkdir(parents=True, exist_ok=True)
        return str(output_path)
    
    def upload_job_results(self, job_id: str, results_dir: str) -> str:
        """
        Copy results from processing directory to job output storage.
        
        If results_dir is already the output directory (NFS case), 
        this just updates metadata.
        
        Args:
            job_id: Job identifier
            results_dir: Directory containing result files
            
        Returns:
            Path to the output directory in storage
        """
        output_path = self._get_output_path(job_id)
        results_path = Path(results_dir)
        
        output_path.mkdir(parents=True, exist_ok=True)
        
        result_files = []
        
        # Walk through results directory
        for root, dirs, files in os.walk(results_dir):
            for filename in files:
                src_file = Path(root) / filename
                rel_path = src_file.relative_to(results_path)
                
                # If results_dir is same as output_path, don't copy
                if results_path != output_path:
                    dst_file = output_path / rel_path
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    file_path = str(dst_file)
                else:
                    file_path = str(src_file)
                
                result_files.append({
                    "filename": str(rel_path),
                    "size": src_file.stat().st_size,
                    "uploaded_at": datetime.now(timezone.utc).isoformat()
                })
        
        # Update metadata
        metadata = self._load_metadata(job_id) or {
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_files": [],
            "output_files": []
        }
        metadata["output_files"] = result_files
        metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
        self._save_metadata(job_id, metadata)
        
        logger.info(f"Stored {len(result_files)} result files for job {job_id}")
        return str(output_path)
    
    def get_job_files(self, job_id: str, file_type: str = "output") -> List[Dict[str, Any]]:
        """
        List files for a job.
        
        Args:
            job_id: Job identifier
            file_type: Either 'input' or 'output'
            
        Returns:
            List of file info dicts with filename, size, path
        """
        if file_type == "input":
            dir_path = self._get_input_path(job_id)
        else:
            dir_path = self._get_output_path(job_id)
        
        if not dir_path.exists():
            return []
        
        files = []
        for file_path in dir_path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(dir_path)
                files.append({
                    "filename": str(rel_path),
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        file_path.stat().st_mtime, 
                        tz=timezone.utc
                    ).isoformat()
                })
        
        return files
    
    def get_file_path(self, job_id: str, filename: str, file_type: str = "output") -> Optional[str]:
        """
        Get the full path to a specific file.
        
        Args:
            job_id: Job identifier
            filename: Name of the file (can include subdirectories)
            file_type: Either 'input' or 'output'
            
        Returns:
            Full path to file, or None if not found
        """
        if file_type == "input":
            dir_path = self._get_input_path(job_id)
        else:
            dir_path = self._get_output_path(job_id)
        
        file_path = dir_path / filename
        
        if file_path.exists():
            return str(file_path)
        
        return None
    
    def delete_job_files(self, job_id: str) -> bool:
        """
        Delete all files for a job (both input and output).
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if deletion successful
        """
        try:
            job_path = self._get_job_path(job_id)
            
            if job_path.exists():
                shutil.rmtree(job_path)
                logger.info(f"Deleted all files for job {job_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete files for job {job_id}: {e}")
            return False
    
    def cleanup_old_jobs(self, retention_hours: float = 72) -> int:
        """
        Delete job files older than the specified retention period.
        
        Args:
            retention_hours: Hours to retain job files (supports fractional hours for testing)
            
        Returns:
            Number of jobs cleaned up
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        cleaned_count = 0
        
        if not self.jobs_path.exists():
            return 0
        
        for job_dir in self.jobs_path.iterdir():
            if not job_dir.is_dir():
                continue
            
            job_id = job_dir.name
            metadata = self._load_metadata(job_id)
            
            # Determine job age from metadata or directory mtime
            if metadata and "created_at" in metadata:
                try:
                    created_at = datetime.fromisoformat(metadata["created_at"])
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    # Fall back to directory modification time
                    created_at = datetime.fromtimestamp(
                        job_dir.stat().st_mtime, 
                        tz=timezone.utc
                    )
            else:
                created_at = datetime.fromtimestamp(
                    job_dir.stat().st_mtime, 
                    tz=timezone.utc
                )
            
            if created_at < cutoff_time:
                try:
                    shutil.rmtree(job_dir)
                    cleaned_count += 1
                    logger.debug(f"Cleaned up old job files: {job_id}")
                except Exception as e:
                    logger.error(f"Failed to clean up job {job_id}: {e}")
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up files for {cleaned_count} old jobs")
        
        return cleaned_count
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.
        
        Returns:
            Dict with storage stats (total_jobs, total_size, etc.)
        """
        total_jobs = 0
        total_size = 0
        input_size = 0
        output_size = 0
        
        if self.jobs_path.exists():
            for job_dir in self.jobs_path.iterdir():
                if not job_dir.is_dir():
                    continue
                
                total_jobs += 1
                
                # Calculate sizes
                for file_path in job_dir.rglob("*"):
                    if file_path.is_file():
                        size = file_path.stat().st_size
                        total_size += size
                        
                        if "input" in str(file_path):
                            input_size += size
                        elif "output" in str(file_path):
                            output_size += size
        
        # Get disk usage for storage path
        try:
            stat = shutil.disk_usage(self.storage_path)
            disk_total = stat.total
            disk_used = stat.used
            disk_free = stat.free
        except Exception:
            disk_total = disk_used = disk_free = 0
        
        return {
            "storage_path": str(self.storage_path),
            "total_jobs": total_jobs,
            "total_size_bytes": total_size,
            "total_size_human": self._human_readable_size(total_size),
            "input_size_bytes": input_size,
            "output_size_bytes": output_size,
            "disk_total_bytes": disk_total,
            "disk_used_bytes": disk_used,
            "disk_free_bytes": disk_free,
            "disk_free_human": self._human_readable_size(disk_free)
        }
    
    @staticmethod
    def _human_readable_size(size_bytes: int) -> str:
        """Convert bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"


# Global storage manager instance
_storage_manager: Optional[LocalStorageManager] = None


def get_storage_manager(storage_path: Optional[str] = None) -> LocalStorageManager:
    """
    Get the global storage manager instance.
    
    Args:
        storage_path: Optional path to override default storage location.
                     If not provided, uses STORAGE_PATH env var or default.
    
    Returns:
        LocalStorageManager instance
    """
    global _storage_manager
    
    if _storage_manager is None:
        if storage_path is None:
            storage_path = os.environ.get("STORAGE_PATH", "/data/grinn-jobs")
        _storage_manager = LocalStorageManager(storage_path)
    
    return _storage_manager


def reset_storage_manager():
    """Reset the global storage manager instance (useful for testing)."""
    global _storage_manager
    _storage_manager = None
