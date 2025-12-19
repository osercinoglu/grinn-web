"""
Database models for gRINN Web Service job management.
Uses SQLAlchemy ORM for database operations.
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Float, Boolean, JSON, text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Import local modules
import hruid

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
    EXPIRED = "expired"

class JobModel(Base):
    """Database model for gRINN analysis jobs."""
    __tablename__ = "jobs"
    
    # Primary identification - human-readable job ID (e.g., '6-sad-squid-snuggle-softly')
    id = Column(String(100), primary_key=True, default=lambda: hruid.Generator().random())
    job_name = Column(String(255), nullable=True)  # Optional user-provided name
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
    results_gcs_path = Column(String(500))  # Path to results (legacy field name)
    
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
            'results_path': self.results_gcs_path,  # New name, legacy column
            'results_gcs_path': self.results_gcs_path,  # Keep for backward compatibility
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
    
    @property
    def is_expired(self) -> bool:
        """Check if job has expired (files deleted but record remains)."""
        return self.status == JobStatus.EXPIRED.value


class WorkerModel(Base):
    """Database model for computational workers."""
    __tablename__ = "workers"
    
    worker_id = Column(String(255), primary_key=True)
    facility_name = Column(String(255), nullable=True)
    hostname = Column(String(255), nullable=True)
    max_concurrent_jobs = Column(Integer, nullable=False, default=2)
    current_job_count = Column(Integer, nullable=False, default=0)
    available_gromacs_versions = Column(Text, nullable=True)  # JSON string
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), nullable=False, default='online')  # online, offline, error
    registered_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_workers_last_heartbeat', 'last_heartbeat'),
        Index('idx_workers_status', 'status'),
        Index('idx_workers_capacity', 'status', 'current_job_count', 'max_concurrent_jobs'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert worker model to dictionary."""
        import json
        gromacs_versions = []
        if self.available_gromacs_versions:
            try:
                gromacs_versions = json.loads(self.available_gromacs_versions)
            except:
                pass
        
        return {
            'worker_id': self.worker_id,
            'facility_name': self.facility_name,
            'hostname': self.hostname,
            'max_concurrent_jobs': self.max_concurrent_jobs,
            'current_job_count': self.current_job_count,
            'available_gromacs_versions': gromacs_versions,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'status': self.status,
            'registered_at': self.registered_at.isoformat() if self.registered_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ChatTokenUsageModel(Base):
    """Database model for chat token usage tracking per job."""
    __tablename__ = "chat_token_usage"
    
    job_id = Column(String(255), primary_key=True)
    tokens_used = Column(Integer, nullable=False, default=0)
    token_limit = Column(Integer, nullable=False, default=100000)
    last_updated = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_chat_token_usage_job_id', 'job_id'),
        Index('idx_chat_token_usage_updated', 'last_updated'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert token usage model to dictionary."""
        return {
            'job_id': self.job_id,
            'tokens_used': self.tokens_used,
            'token_limit': self.token_limit,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


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
    
    def set_job_results(self, job_id: str, results_path: str) -> bool:
        """Set job results path (stored in results_gcs_path field for compatibility)."""
        with self.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return False
            
            job.results_gcs_path = results_path
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
    
    def count_queued_jobs(self) -> int:
        """Count jobs that are queued or pending (waiting to be processed)."""
        with self.get_session() as session:
            return session.query(JobModel).filter(
                JobModel.status.in_([
                    JobStatus.PENDING.value,
                    JobStatus.UPLOADING.value,
                    JobStatus.QUEUED.value
                ])
            ).count()
    
    def cleanup_old_jobs(self, days_old: int = 7) -> int:
        """
        Legacy method - now just marks jobs as expired.
        Use mark_jobs_as_expired() and delete_expired_jobs() instead.
        """
        return self.mark_jobs_as_expired(hours_old=days_old * 24)
    
    def mark_jobs_as_expired(self, hours_old: float = 72) -> int:
        """
        Mark terminal jobs (completed/failed/cancelled) as expired after retention period.
        Files should be deleted before calling this method.
        
        Args:
            hours_old: Jobs older than this many hours will be marked expired (supports fractional hours)
            
        Returns:
            Number of jobs marked as expired
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(hours=hours_old)
        
        with self.get_session() as session:
            # Only mark completed, failed, or cancelled jobs as expired
            expired_count = session.query(JobModel).filter(
                JobModel.created_at < cutoff_date,
                JobModel.status.in_([
                    JobStatus.COMPLETED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value
                ])
            ).update({JobModel.status: JobStatus.EXPIRED.value}, synchronize_session=False)
            session.commit()
            return expired_count
    
    def delete_expired_jobs(self, days_old: int = 30) -> int:
        """
        Permanently delete expired job records from the database.
        
        Args:
            days_old: Expired jobs older than this many days will be deleted
            
        Returns:
            Number of jobs deleted
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        
        with self.get_session() as session:
            deleted_count = session.query(JobModel).filter(
                JobModel.created_at < cutoff_date,
                JobModel.status == JobStatus.EXPIRED.value
            ).delete()
            session.commit()
            return deleted_count
    
    # Worker management methods
    
    def register_worker(self, worker_id: str, facility_name: str = None, hostname: str = None,
                       max_concurrent_jobs: int = 2, available_gromacs_versions: List[str] = None) -> WorkerModel:
        """Register a new worker or update existing worker."""
        import json
        
        with self.get_session() as session:
            worker = session.query(WorkerModel).filter(WorkerModel.worker_id == worker_id).first()
            
            if worker:
                # Update existing worker
                worker.facility_name = facility_name
                worker.hostname = hostname
                worker.max_concurrent_jobs = max_concurrent_jobs
                worker.available_gromacs_versions = json.dumps(available_gromacs_versions or [])
                worker.last_heartbeat = datetime.now(timezone.utc)
                worker.status = 'online'
                worker.updated_at = datetime.now(timezone.utc)
            else:
                # Create new worker
                worker = WorkerModel(
                    worker_id=worker_id,
                    facility_name=facility_name,
                    hostname=hostname,
                    max_concurrent_jobs=max_concurrent_jobs,
                    available_gromacs_versions=json.dumps(available_gromacs_versions or []),
                    last_heartbeat=datetime.now(timezone.utc),
                    status='online'
                )
                session.add(worker)
            
            session.commit()
            session.refresh(worker)
            session.expunge(worker)
            return worker
    
    def update_worker_heartbeat(self, worker_id: str, current_job_count: int = None) -> bool:
        """Update worker heartbeat timestamp and optionally job count."""
        with self.get_session() as session:
            worker = session.query(WorkerModel).filter(WorkerModel.worker_id == worker_id).first()
            if not worker:
                return False
            
            worker.last_heartbeat = datetime.now(timezone.utc)
            worker.status = 'online'
            if current_job_count is not None:
                worker.current_job_count = current_job_count
            worker.updated_at = datetime.now(timezone.utc)
            
            session.commit()
            return True
    
    def get_worker(self, worker_id: str) -> Optional[WorkerModel]:
        """Get worker by ID."""
        with self.get_session() as session:
            worker = session.query(WorkerModel).filter(WorkerModel.worker_id == worker_id).first()
            if worker:
                session.expunge(worker)
            return worker
    
    def get_all_workers(self) -> List[WorkerModel]:
        """Get all registered workers."""
        with self.get_session() as session:
            workers = session.query(WorkerModel).all()
            for worker in workers:
                session.expunge(worker)
            return workers
    
    def get_online_workers(self, timeout_seconds: int = 90) -> List[WorkerModel]:
        """Get workers that have sent heartbeat within timeout period."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        
        with self.get_session() as session:
            workers = session.query(WorkerModel).filter(
                WorkerModel.status == 'online',
                WorkerModel.last_heartbeat >= cutoff_time
            ).all()
            for worker in workers:
                session.expunge(worker)
            return workers
    
    def get_available_workers(self, timeout_seconds: int = 90) -> List[WorkerModel]:
        """Get workers with available capacity."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        
        with self.get_session() as session:
            workers = session.query(WorkerModel).filter(
                WorkerModel.status == 'online',
                WorkerModel.last_heartbeat >= cutoff_time,
                WorkerModel.current_job_count < WorkerModel.max_concurrent_jobs
            ).all()
            for worker in workers:
                session.expunge(worker)
            return workers
    
    def mark_workers_offline(self, timeout_seconds: int = 90) -> int:
        """Mark workers as offline if they haven't sent heartbeat within timeout."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        
        with self.get_session() as session:
            count = session.query(WorkerModel).filter(
                WorkerModel.status == 'online',
                WorkerModel.last_heartbeat < cutoff_time
            ).update({WorkerModel.status: 'offline'}, synchronize_session=False)
            session.commit()
            return count
    
    def increment_worker_job_count(self, worker_id: str) -> bool:
        """Increment worker's current job count."""
        with self.get_session() as session:
            worker = session.query(WorkerModel).filter(WorkerModel.worker_id == worker_id).first()
            if not worker:
                return False
            worker.current_job_count += 1
            session.commit()
            return True
    
    def decrement_worker_job_count(self, worker_id: str) -> bool:
        """Decrement worker's current job count."""
        with self.get_session() as session:
            worker = session.query(WorkerModel).filter(WorkerModel.worker_id == worker_id).first()
            if not worker:
                return False
            worker.current_job_count = max(0, worker.current_job_count - 1)
            session.commit()
            return True
    
    def get_jobs_by_worker(self, worker_id: str) -> List[JobModel]:
        """Get all active jobs assigned to a worker."""
        with self.get_session() as session:
            jobs = session.query(JobModel).filter(
                JobModel.worker_id == worker_id,
                JobModel.status.in_([
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value
                ])
            ).all()
            for job in jobs:
                session.expunge(job)
            return jobs
    
    # Chat token usage methods
    
    def create_token_usage(self, job_id: str, token_limit: int = 100000) -> ChatTokenUsageModel:
        """Create token usage record for a job."""
        with self.get_session() as session:
            usage = ChatTokenUsageModel(
                job_id=job_id,
                tokens_used=0,
                token_limit=token_limit
            )
            session.add(usage)
            session.commit()
            session.refresh(usage)
            session.expunge(usage)
            return usage
    
    def get_token_usage(self, job_id: str) -> Optional[ChatTokenUsageModel]:
        """Get token usage for a job."""
        with self.get_session() as session:
            usage = session.query(ChatTokenUsageModel).filter(ChatTokenUsageModel.job_id == job_id).first()
            if usage:
                session.expunge(usage)
            return usage
    
    def update_token_usage(self, job_id: str, tokens_used: int) -> bool:
        """Update token usage for a job."""
        with self.get_session() as session:
            usage = session.query(ChatTokenUsageModel).filter(ChatTokenUsageModel.job_id == job_id).first()
            if not usage:
                # Create if doesn't exist
                usage = ChatTokenUsageModel(
                    job_id=job_id,
                    tokens_used=tokens_used
                )
                session.add(usage)
            else:
                usage.tokens_used = tokens_used
                usage.last_updated = datetime.now(timezone.utc)
            
            session.commit()
            return True
    
    def reset_token_usage(self, job_id: str) -> bool:
        """Reset token usage for a job (admin operation)."""
        with self.get_session() as session:
            usage = session.query(ChatTokenUsageModel).filter(ChatTokenUsageModel.job_id == job_id).first()
            if not usage:
                return False
            
            usage.tokens_used = 0
            usage.last_updated = datetime.now(timezone.utc)
            session.commit()
            return True

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