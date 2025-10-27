"""
Database models for gRINN Web Service job management.
Uses SQLAlchemy ORM for database operations.
"""

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Float, Boolean, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.dialects.postgresql import UUID

# Setup logging
logger = logging.getLogger(__name__)

# Database models
Base = declarative_base()

class JobStatus(str, Enum):
    """Job status enumeration."""
    PENDING = "pending"
    UPLOADING = "uploading"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class JobModel(Base):
    """Database model for gRINN analysis jobs."""
    __tablename__ = "jobs"
    
    # Primary identification
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_name = Column(String(255), nullable=False)
    description = Column(Text)
    user_email = Column(String(255))
    is_private = Column(Boolean, default=False, nullable=False)
    
    # Job status and timing
    status = Column(String(20), nullable=False, default=JobStatus.PENDING.value)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    
    # Progress tracking
    progress_percentage = Column(Integer, default=0)
    current_step = Column(String(500))
    error_message = Column(Text)
    
    # Job parameters (stored as JSON)
    parameters = Column(JSON)
    
    # File information
    input_files = Column(JSON)  # List of uploaded files metadata
    results_gcs_path = Column(String(500))  # GCS path to results
    
    # Worker information
    worker_id = Column(String(100))  # Celery task ID
    worker_host = Column(String(100))  # Worker hostname
    
    # Resource usage tracking
    processing_time_seconds = Column(Integer)
    memory_usage_mb = Column(Integer)
    cpu_usage_percent = Column(Float)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job model to dictionary."""
        return {
            'job_id': self.id,
            'job_name': self.job_name,
            'description': self.description,
            'user_email': self.user_email,
            'is_private': self.is_private,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'progress_percentage': self.progress_percentage,
            'current_step': self.current_step,
            'error_message': self.error_message,
            'parameters': self.parameters,
            'input_files': self.input_files,
            'results_gcs_path': self.results_gcs_path,
            'worker_id': self.worker_id,
            'worker_host': self.worker_host,
            'processing_time_seconds': self.processing_time_seconds,
            'memory_usage_mb': self.memory_usage_mb,
            'cpu_usage_percent': self.cpu_usage_percent
        }
    
    @property
    def duration_seconds(self) -> Optional[int]:
        """Calculate job duration in seconds."""
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds())
        elif self.started_at:
            return int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        return None
    
    @property
    def is_active(self) -> bool:
        """Check if job is currently active (running or queued)."""
        return self.status in [JobStatus.PENDING.value, JobStatus.UPLOADING.value, 
                              JobStatus.QUEUED.value, JobStatus.RUNNING.value]
    
    @property
    def is_completed(self) -> bool:
        """Check if job is completed successfully."""
        return self.status == JobStatus.COMPLETED.value
    
    @property
    def has_failed(self) -> bool:
        """Check if job has failed."""
        return self.status in [JobStatus.FAILED.value, JobStatus.CANCELLED.value]

class DatabaseManager:
    """Database manager for gRINN Web Service."""
    
    def __init__(self, database_url: str = None):
        """Initialize the database manager with connection URL."""
        self.database_url = database_url or get_database_url()
        self.engine = create_engine(self.database_url, echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    def init_db(self):
        """Initialize the database by creating all tables."""
        try:
            JobModel.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise
            
    def test_connection(self):
        """Test database connection."""
        try:
            with self.get_session() as session:
                result = session.execute(text("SELECT 1"))
                return result is not None
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
        
    def create_tables(self):
        """Create all database tables."""
        Base.metadata.create_all(bind=self.engine)
        
    @contextmanager
    def get_session(self) -> Session:
        """Get database session as a context manager."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def create_job(self, job_name: str, description: str = None, user_email: str = None,
                   parameters: Dict[str, Any] = None, input_files: List[Dict] = None) -> JobModel:
        """Create a new job record."""
        with self.get_session() as session:
            job = JobModel(
                job_name=job_name,
                description=description,
                user_email=user_email,
                parameters=parameters or {},
                input_files=input_files or []
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job
    
    def get_job(self, job_id: str) -> Optional[JobModel]:
        """Get job by ID."""
        with self.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if job:
                # Force load all attributes before expunging to avoid lazy load issues
                # Access all attributes to trigger loading
                _ = job.id, job.status, job.parameters, job.input_files
                _ = job.job_name, job.description, job.created_at, job.started_at
                _ = job.completed_at, job.progress_percentage, job.current_step
                _ = job.error_message, job.results_gcs_path, job.user_email
                _ = job.worker_id, job.worker_host, job.is_private
                _ = job.processing_time_seconds, job.memory_usage_mb, job.cpu_usage_percent
                
                # Expunge the object from session to avoid detached session issues
                session.expunge(job)
            return job
    
    def update_job_status(self, job_id: str, status: JobStatus, current_step: str = None,
                         progress_percentage: int = None, error_message: str = None) -> bool:
        """Update job status and progress."""
        with self.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return False
            
            job.status = status.value
            if current_step:
                job.current_step = current_step
            if progress_percentage is not None:
                job.progress_percentage = progress_percentage
            if error_message:
                job.error_message = error_message
            
            # Update timestamps
            now = datetime.now(timezone.utc)
            if status == JobStatus.RUNNING and not job.started_at:
                job.started_at = now
            elif status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                if not job.completed_at:
                    job.completed_at = now
            
            session.commit()
            return True
    
    def set_job_results(self, job_id: str, results_gcs_path: str) -> bool:
        """Set job results path."""
        with self.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return False
            
            job.results_gcs_path = results_gcs_path
            session.commit()
            return True
    
    def set_worker_info(self, job_id: str, worker_id: str, worker_host: str = None) -> bool:
        """Set worker information for job."""
        with self.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return False
            
            job.worker_id = worker_id
            if worker_host:
                job.worker_host = worker_host
            session.commit()
            return True
    
    def get_jobs_by_status(self, status: JobStatus, limit: int = 100) -> List[JobModel]:
        """Get jobs by status."""
        with self.get_session() as session:
            return session.query(JobModel).filter(JobModel.status == status.value).limit(limit).all()
    
    def get_recent_jobs(self, limit: int = 50) -> List[JobModel]:
        """Get recent jobs ordered by creation time."""
        with self.get_session() as session:
            return session.query(JobModel).order_by(JobModel.created_at.desc()).limit(limit).all()
    
    def get_active_jobs(self) -> List[JobModel]:
        """Get all active (running/queued) jobs."""
        with self.get_session() as session:
            return session.query(JobModel).filter(
                JobModel.status.in_([
                    JobStatus.PENDING.value,
                    JobStatus.UPLOADING.value,
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value
                ])
            ).all()
    
    def cleanup_old_jobs(self, days_old: int = 7) -> int:
        """Clean up jobs older than specified days."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        
        with self.get_session() as session:
            # Only delete completed, failed, or cancelled jobs
            deleted_count = session.query(JobModel).filter(
                JobModel.created_at < cutoff_date,
                JobModel.status.in_([
                    JobStatus.COMPLETED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value
                ])
            ).delete()
            session.commit()
            return deleted_count

def get_database_url() -> str:
    """Get database URL from environment."""
    # Default to SQLite for development
    default_url = "sqlite:///grinn_web.db"
    
    # Check for PostgreSQL configuration
    if all(key in os.environ for key in ['DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']):
        return f"postgresql://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}@{os.environ['DB_HOST']}/{os.environ['DB_NAME']}"
    
    return os.environ.get('DATABASE_URL', default_url)

def get_database_manager() -> DatabaseManager:
    """Get configured database manager instance."""
    database_url = get_database_url()
    manager = DatabaseManager(database_url)
    manager.create_tables()  # Ensure tables exist
    return manager