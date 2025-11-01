"""
Data models and schemas for gRINN Web Service.
Defines job structure, validation, and data transfer objects.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

import hruid

class JobStatus(Enum):
    """Job status enumeration."""
    PENDING = "pending"
    UPLOADING = "uploading"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class FileType(Enum):
    """Supported input file types."""
    PDB = "pdb"
    XTC = "xtc"
    TRR = "trr"  # Additional trajectory format
    TPR = "tpr"
    GRO = "gro"
    TOP = "top"
    ITP = "itp"
    RTP = "rtp"  # Topology description files
    PRM = "prm"  # Parameter files (CHARMM/AMBER force field parameters)
    ZIP = "zip"  # Compressed archive (for force field folders)
    DIR = "dir"  # Force field directory (virtual type for folder uploads)

@dataclass
class JobFile:
    """Represents an uploaded file for a job."""
    filename: str
    file_type: FileType
    size_bytes: int
    gcs_path: Optional[str] = None
    upload_timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if self.upload_timestamp is None:
            self.upload_timestamp = datetime.utcnow()

@dataclass
class JobParameters:
    """gRINN job execution parameters for trajectory analysis."""
    # Trajectory analysis parameters
    skip_frames: int = 1
    initpairfilter_cutoff: float = 12.0
    
    # Selection parameters
    source_sel: Optional[str] = None  # Source residue selection
    target_sel: Optional[str] = None  # Target residue selection
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert parameters to dictionary."""
        return {
            "skip_frames": self.skip_frames,
            "initpairfilter_cutoff": self.initpairfilter_cutoff,
            "source_sel": self.source_sel,
            "target_sel": self.target_sel
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobParameters":
        """Create parameters from dictionary."""
        return cls(**data)

@dataclass 
class Job:
    """Represents a gRINN computational job."""
    job_id: str = field(default_factory=lambda: hruid.Generator().random())
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # User information
    user_email: Optional[str] = None
    user_ip: Optional[str] = None
    
    # Job configuration
    job_name: Optional[str] = None
    description: Optional[str] = None
    is_private: bool = False  # Whether job details should be hidden in public queue
    parameters: JobParameters = field(default_factory=JobParameters)
    
    # Files
    input_files: List[JobFile] = field(default_factory=list)
    
    # Execution information
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    worker_id: Optional[str] = None
    
    # Results
    results_gcs_path: Optional[str] = None
    error_message: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    
    # Progress tracking
    progress_percentage: float = 0.0
    current_step: Optional[str] = None
    
    def update_status(self, status: JobStatus, message: Optional[str] = None):
        """Update job status with timestamp."""
        self.status = status
        self.updated_at = datetime.utcnow()
        
        if status == JobStatus.RUNNING and self.started_at is None:
            self.started_at = datetime.utcnow()
        elif status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            self.completed_at = datetime.utcnow()
        
        if status == JobStatus.FAILED and message:
            self.error_message = message
    
    def add_file(self, filename: str, file_type: FileType, size_bytes: int) -> JobFile:
        """Add a file to the job."""
        job_file = JobFile(
            filename=filename,
            file_type=file_type,
            size_bytes=size_bytes
        )
        self.input_files.append(job_file)
        return job_file
    
    def get_file_by_type(self, file_type: FileType) -> Optional[JobFile]:
        """Get the first file of a specific type."""
        for file in self.input_files:
            if file.file_type == file_type:
                return file
        return None
    
    def get_files_by_type(self, file_type: FileType) -> List[JobFile]:
        """Get all files of a specific type."""
        return [file for file in self.input_files if file.file_type == file_type]
    
    def total_file_size(self) -> int:
        """Get total size of all uploaded files in bytes."""
        return sum(file.size_bytes for file in self.input_files)
    
    def duration_seconds(self) -> Optional[float]:
        """Get job duration in seconds if completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for serialization."""
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "user_email": self.user_email,
            "user_ip": self.user_ip,
            "job_name": self.job_name,
            "description": self.description,
            "parameters": self.parameters.to_dict(),
            "input_files": [
                {
                    "filename": f.filename,
                    "file_type": f.file_type.value,
                    "size_bytes": f.size_bytes,
                    "gcs_path": f.gcs_path,
                    "upload_timestamp": f.upload_timestamp.isoformat() if f.upload_timestamp else None
                } for f in self.input_files
            ],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "worker_id": self.worker_id,
            "results_gcs_path": self.results_gcs_path,
            "error_message": self.error_message,
            "error_details": self.error_details,
            "progress_percentage": self.progress_percentage,
            "current_step": self.current_step
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create job from dictionary."""
        job = cls()
        job.job_id = data["job_id"]
        job.status = JobStatus(data["status"])
        job.created_at = datetime.fromisoformat(data["created_at"])
        job.updated_at = datetime.fromisoformat(data["updated_at"])
        job.user_email = data.get("user_email")
        job.user_ip = data.get("user_ip")
        job.job_name = data.get("job_name")
        job.description = data.get("description")
        job.parameters = JobParameters.from_dict(data["parameters"])
        
        # Restore files
        job.input_files = []
        for file_data in data.get("input_files", []):
            job_file = JobFile(
                filename=file_data["filename"],
                file_type=FileType(file_data["file_type"]),
                size_bytes=file_data["size_bytes"],
                gcs_path=file_data.get("gcs_path")
            )
            if file_data.get("upload_timestamp"):
                job_file.upload_timestamp = datetime.fromisoformat(file_data["upload_timestamp"])
            job.input_files.append(job_file)
        
        # Restore timestamps
        if data.get("started_at"):
            job.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            job.completed_at = datetime.fromisoformat(data["completed_at"])
        
        job.worker_id = data.get("worker_id")
        job.results_gcs_path = data.get("results_gcs_path")
        job.error_message = data.get("error_message")
        job.error_details = data.get("error_details")
        job.progress_percentage = data.get("progress_percentage", 0.0)
        job.current_step = data.get("current_step")
        
        return job


@dataclass
class JobSubmissionRequest:
    """Request object for job submission."""
    job_name: str
    description: Optional[str] = None
    user_email: Optional[str] = None
    is_private: bool = False
    parameters: Optional[Dict[str, Any]] = None
    
    def to_job(self) -> Job:
        """Convert to Job object."""
        job = Job()
        job.job_name = self.job_name
        job.description = self.description
        job.user_email = self.user_email
        job.is_private = self.is_private
        
        if self.parameters:
            job.parameters = JobParameters.from_dict(self.parameters)
        
        return job


@dataclass
class JobResponse:
    """Response object for job operations."""
    success: bool
    job_id: Optional[str] = None
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None