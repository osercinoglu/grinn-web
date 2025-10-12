"""
Celery tasks for gRINN Web Service
Handles computational job processing using Docker containers
"""

import os
import sys
import docker
import tempfile
import shutil
from celery import Celery
from typing import Dict, Any
import logging

# Add parent directory to path for Celery workers to find shared modules
project_root = os.path.dirname(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.database import DatabaseManager
from shared.models import JobStatus
from shared.storage import get_storage_manager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Celery app
celery_app = Celery('grinn_worker')

# Configure Celery
celery_config = {
    'broker_url': 'redis://localhost:6379/0',
    'result_backend': 'redis://localhost:6379/0',
    'task_serializer': 'json',
    'accept_content': ['json'],
    'result_serializer': 'json',
    'timezone': 'UTC',
    'enable_utc': True,
    'worker_prefetch_multiplier': 1,
    'task_acks_late': True,
    'worker_max_tasks_per_child': 1000,
    'task_time_limit': 3600,
}
celery_app.conf.update(celery_config)

# Initialize database and storage
db_manager = DatabaseManager()
storage_manager = get_storage_manager()

@celery_app.task(bind=True)
def process_grinn_job(self, job_id: str, job_params: Dict[str, Any]):
    """
    Process a gRINN computational job using Docker container
    
    Args:
        job_id: Unique job identifier
        job_params: Job parameters including file paths and settings
    """
    # Initialize managers for this worker process
    local_db_manager = DatabaseManager()
    local_storage_manager = get_storage_manager()
    
    try:
        logger.info(f"Starting job {job_id}")
        
        # Update job status to running
        job = local_db_manager.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        # Update job status using the database manager method
        local_db_manager.update_job_status(job_id, JobStatus.RUNNING, "Processing gRINN analysis", 25)
        
        # Create temporary directory for job processing
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = os.path.join(temp_dir, 'input')
            output_dir = os.path.join(temp_dir, 'output')
            os.makedirs(input_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)
            
            # Download input files from storage
            logger.info(f"Downloading input files for job {job_id}")
            structure_path = os.path.join(input_dir, 'structure.pdb')
            trajectory_path = os.path.join(input_dir, 'trajectory.xtc')
            
            local_storage_manager.download_file(
                f"jobs/{job_id}/structure.pdb", 
                structure_path
            )
            local_storage_manager.download_file(
                f"jobs/{job_id}/trajectory.xtc", 
                trajectory_path
            )
            
            # Run gRINN analysis in Docker container
            logger.info(f"Running gRINN analysis for job {job_id}")
            docker_client = docker.from_env()
            
            grinn_image = os.getenv('GRINN_DOCKER_IMAGE', 'grinn:latest')
            
            # Prepare Docker command
            docker_command = [
                'python', '/app/grinn_workflow.py',
                '--structure', '/input/structure.pdb',
                '--trajectory', '/input/trajectory.xtc',
                '--output', '/output',
                '--format', 'json'
            ]
            
            # Add job-specific parameters
            if job_params.get('threshold'):
                docker_command.extend(['--threshold', str(job_params['threshold'])])
            if job_params.get('frames'):
                docker_command.extend(['--frames', str(job_params['frames'])])
            
            # Run container
            container = docker_client.containers.run(
                grinn_image,
                command=docker_command,
                volumes={
                    input_dir: {'bind': '/input', 'mode': 'ro'},
                    output_dir: {'bind': '/output', 'mode': 'rw'}
                },
                remove=True,
                detach=False,
                stdout=True,
                stderr=True
            )
            
            logger.info(f"Container output for job {job_id}: {container.decode()}")
            
            # Upload results to storage
            logger.info(f"Uploading results for job {job_id}")
            result_files = []
            
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, output_dir)
                    storage_path = f"jobs/{job_id}/results/{relative_path}"
                    
                    local_storage_manager.upload_file(local_path, storage_path)
                    result_files.append(storage_path)
            
            # Update job status to completed
            local_db_manager.update_job_status(job_id, JobStatus.COMPLETED, "Job completed successfully", 100)
            
            logger.info(f"Job {job_id} completed successfully")
            return {
                'status': 'completed',
                'result_files': result_files,
                'message': 'Job completed successfully'
            }
            
    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}")
        
        # Update job status to failed
        try:
            local_db_manager.update_job_status(job_id, JobStatus.FAILED, "Job failed", error_message=str(e))
        except Exception as db_error:
            logger.error(f"Failed to update job status: {str(db_error)}")
        
        raise

@celery_app.task
def cleanup_old_jobs():
    """
    Cleanup old jobs and their associated files
    """
    # Initialize managers for this worker process
    local_db_manager = DatabaseManager()
    local_storage_manager = get_storage_manager()
    
    try:
        logger.info("Starting job cleanup")
        
        with local_db_manager.get_session() as session:
            old_jobs = local_db_manager.get_old_jobs(session)
            
            for job in old_jobs:
                try:
                    # Delete files from storage
                    if job.results_gcs_path:
                        local_storage_manager.delete_folder(job.results_gcs_path)
                    
                    # Delete input files
                    local_storage_manager.delete_file(f"jobs/{job.id}/structure.pdb")
                    local_storage_manager.delete_file(f"jobs/{job.id}/trajectory.xtc")
                    
                    # Delete job from database
                    local_db_manager.delete_job(session, job.id)
                    logger.info(f"Cleaned up job {job.id}")
                    
                except Exception as e:
                    logger.error(f"Failed to cleanup job {job.id}: {str(e)}")
            
            session.commit()
            
    except Exception as e:
        logger.error(f"Job cleanup failed: {str(e)}")

# Periodic task to cleanup old jobs (runs daily)
celery_app.conf.beat_schedule = {
    'cleanup-old-jobs': {
        'task': 'backend.tasks.cleanup_old_jobs',
        'schedule': 24 * 60 * 60,  # 24 hours
    },
}
celery_app.conf.timezone = 'UTC'