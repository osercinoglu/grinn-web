"""
Job queue management for gRINN Web Service.
Handles Celery task queue setup and job state management.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import uuid

try:
    from celery import Celery, Task
    from celery.result import AsyncResult
    import redis
    HAS_CELERY = True
except ImportError:
    HAS_CELERY = False
    Celery = None
    redis = None

from shared.config import get_config
from shared.models import Job, JobStatus

logger = logging.getLogger(__name__)
config = get_config()

class JobQueue:
    """Manages job queue operations and job state."""
    
    def __init__(self):
        if not HAS_CELERY:
            raise ImportError("Celery not installed. Install with: pip install celery redis")
        
        # Initialize Celery app
        self.celery_app = Celery('grinn-web')
        self.celery_app.conf.update(
            broker_url=config.celery_broker_url,
            result_backend=config.celery_result_backend,
            task_serializer='json',
            accept_content=['json'],
            result_serializer='json',
            timezone='UTC',
            enable_utc=True,
            task_routes={
                'grinn_web.process_grinn_job': {'queue': 'grinn_jobs'},
            },
            worker_prefetch_multiplier=1,
            task_acks_late=True,
            worker_max_tasks_per_child=1,  # Restart worker after each task to clean up Docker
        )
        
        # Initialize Redis for job state management
        try:
            self.redis_client = redis.Redis(
                host=config.redis_host,
                port=config.redis_port,
                db=config.redis_db,
                decode_responses=True
            )
            self.redis_client.ping()
            logger.info("Successfully connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
        
        self.job_prefix = "grinn_job:"
        self.job_list_key = "grinn_jobs:list"
    
    def submit_job(self, job: Job) -> str:
        """
        Submit a job to the processing queue.
        
        Args:
            job: Job object to submit
            
        Returns:
            Celery task ID
        """
        try:
            # Update job status
            job.update_status(JobStatus.QUEUED, "Job queued for processing")
            
            # Store job state
            self.store_job(job)
            
            # Submit to Celery
            task = self.celery_app.send_task(
                'grinn_web.process_grinn_job',
                args=[job.job_id],
                queue='grinn_jobs',
                task_id=f"grinn_{job.job_id}"
            )
            
            # Update job with task ID
            job.worker_id = task.id
            self.store_job(job)
            
            logger.info(f"Submitted job {job.job_id} to queue with task ID {task.id}")
            return task.id
            
        except Exception as e:
            logger.error(f"Failed to submit job {job.job_id}: {e}")
            job.update_status(JobStatus.FAILED, f"Failed to submit job: {str(e)}")
            self.store_job(job)
            raise
    
    def store_job(self, job: Job):
        """Store job state in Redis."""
        try:
            job_key = f"{self.job_prefix}{job.job_id}"
            job_data = json.dumps(job.to_dict())
            
            # Store job data
            self.redis_client.set(job_key, job_data)
            
            # Add to job list if not already present
            self.redis_client.sadd(self.job_list_key, job.job_id)
            
            # Set expiration based on job retention policy
            expiration_seconds = config.job_retention_days * 24 * 3600
            self.redis_client.expire(job_key, expiration_seconds)
            
            logger.debug(f"Stored job {job.job_id} in Redis")
            
        except Exception as e:
            logger.error(f"Failed to store job {job.job_id}: {e}")
            raise
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve job from Redis."""
        try:
            job_key = f"{self.job_prefix}{job_id}"
            job_data = self.redis_client.get(job_key)
            
            if not job_data:
                return None
            
            job_dict = json.loads(job_data)
            return Job.from_dict(job_dict)
            
        except Exception as e:
            logger.error(f"Failed to retrieve job {job_id}: {e}")
            return None
    
    def get_all_jobs(self) -> List[Job]:
        """Get all jobs from Redis."""
        try:
            job_ids = self.redis_client.smembers(self.job_list_key)
            jobs = []
            
            for job_id in job_ids:
                job = self.get_job(job_id)
                if job:
                    jobs.append(job)
            
            # Sort by creation time (newest first)
            jobs.sort(key=lambda x: x.created_at, reverse=True)
            return jobs
            
        except Exception as e:
            logger.error(f"Failed to retrieve all jobs: {e}")
            return []
    
    def update_job_status(self, job_id: str, status: JobStatus, 
                         message: Optional[str] = None, 
                         progress: Optional[float] = None,
                         current_step: Optional[str] = None):
        """Update job status and progress."""
        try:
            job = self.get_job(job_id)
            if not job:
                logger.warning(f"Job {job_id} not found for status update")
                return
            
            job.update_status(status, message)
            
            if progress is not None:
                job.progress_percentage = progress
            
            if current_step is not None:
                job.current_step = current_step
            
            self.store_job(job)
            logger.debug(f"Updated job {job_id} status to {status.value}")
            
        except Exception as e:
            logger.error(f"Failed to update job {job_id} status: {e}")
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job."""
        try:
            job = self.get_job(job_id)
            if not job:
                logger.warning(f"Job {job_id} not found for cancellation")
                return False
            
            # Only cancel if job is in cancellable state
            if job.status not in [JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING]:
                logger.warning(f"Job {job_id} is in {job.status.value} state and cannot be cancelled")
                return False
            
            # Revoke Celery task if it exists
            if job.worker_id:
                self.celery_app.control.revoke(job.worker_id, terminate=True)
                logger.info(f"Revoked Celery task {job.worker_id} for job {job_id}")
            
            # Update job status
            job.update_status(JobStatus.CANCELLED, "Job cancelled by user")
            self.store_job(job)
            
            logger.info(f"Successfully cancelled job {job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return False
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get current job status and progress."""
        try:
            job = self.get_job(job_id)
            if not job:
                return None
            
            status_info = {
                'job_id': job.job_id,
                'status': job.status.value,
                'progress_percentage': job.progress_percentage,
                'current_step': job.current_step,
                'created_at': job.created_at.isoformat(),
                'updated_at': job.updated_at.isoformat(),
                'error_message': job.error_message
            }
            
            # Add timing information
            if job.started_at:
                status_info['started_at'] = job.started_at.isoformat()
            
            if job.completed_at:
                status_info['completed_at'] = job.completed_at.isoformat()
                status_info['duration_seconds'] = job.duration_seconds()
            elif job.started_at:
                # Calculate current duration
                duration = datetime.utcnow() - job.started_at
                status_info['duration_seconds'] = duration.total_seconds()
            
            # Check Celery task status if available
            if job.worker_id:
                try:
                    task_result = AsyncResult(job.worker_id, app=self.celery_app)
                    status_info['celery_status'] = task_result.status
                    if task_result.info:
                        status_info['celery_info'] = task_result.info
                except Exception:
                    pass  # Ignore Celery status errors
            
            return status_info
            
        except Exception as e:
            logger.error(f"Failed to get status for job {job_id}: {e}")
            return None
    
    def cleanup_old_jobs(self):
        """Clean up old jobs based on retention policy."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=config.job_retention_days)
            
            job_ids = list(self.redis_client.smembers(self.job_list_key))
            cleaned_count = 0
            
            for job_id in job_ids:
                job = self.get_job(job_id)
                if job and job.created_at < cutoff_date:
                    # Remove from Redis
                    job_key = f"{self.job_prefix}{job_id}"
                    self.redis_client.delete(job_key)
                    self.redis_client.srem(self.job_list_key, job_id)
                    
                    # TODO: Clean up GCS files
                    # get_storage_manager().delete_job_files(job_id)
                    
                    cleaned_count += 1
                    logger.debug(f"Cleaned up old job {job_id}")
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} old jobs")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old jobs: {e}")
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        try:
            # Get active jobs by status
            jobs = self.get_all_jobs()
            stats = {
                'total_jobs': len(jobs),
                'by_status': {}
            }
            
            for status in JobStatus:
                count = sum(1 for job in jobs if job.status == status)
                stats['by_status'][status.value] = count
            
            # Get Celery queue stats
            try:
                inspect = self.celery_app.control.inspect()
                active_tasks = inspect.active()
                reserved_tasks = inspect.reserved()
                
                stats['celery'] = {
                    'active_tasks': len(active_tasks) if active_tasks else 0,
                    'reserved_tasks': len(reserved_tasks) if reserved_tasks else 0
                }
            except Exception:
                stats['celery'] = {'error': 'Unable to get Celery stats'}
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {'error': str(e)}


# Global queue manager instance
_queue_manager = None

def get_queue_manager() -> JobQueue:
    """Get the global queue manager instance."""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = JobQueue()
    return _queue_manager


# Utility functions for easy access
def submit_job(job: Job) -> str:
    """Submit a job using the global queue manager."""
    return get_queue_manager().submit_job(job)

def get_job(job_id: str) -> Optional[Job]:
    """Get a job using the global queue manager."""
    return get_queue_manager().get_job(job_id)

def get_all_jobs() -> List[Job]:
    """Get all jobs using the global queue manager."""
    return get_queue_manager().get_all_jobs()

def update_job_status(job_id: str, status: JobStatus, message: Optional[str] = None, 
                     progress: Optional[float] = None, current_step: Optional[str] = None):
    """Update job status using the global queue manager."""
    return get_queue_manager().update_job_status(job_id, status, message, progress, current_step)

def cancel_job(job_id: str) -> bool:
    """Cancel a job using the global queue manager."""
    return get_queue_manager().cancel_job(job_id)