"""
Celery worker for processing gRINN computational jobs.
Handles the complete lifecycle of job processing including file download,
Docker execution, and result upload.
"""

import os
import sys
import logging
import tempfile
import shutil
import subprocess
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional

# Add shared modules to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

from celery import Celery
from models import Job, JobStatus, FileType
from config import get_config, setup_logging
from storage import get_storage_manager
from queue import get_queue_manager

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Get configuration
config = get_config()

# Initialize Celery app
app = Celery('grinn-web')
app.conf.update(
    broker_url=config.celery_broker_url,
    result_backend=config.celery_result_backend,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

class GrinnDockerRunner:
    """Handles execution of gRINN in Docker containers."""
    
    def __init__(self):
        self.docker_image = config.grinn_docker_image
        self.timeout = config.docker_timeout
        
    def run_grinn_analysis(self, input_dir: str, output_dir: str, 
                          job_params: Dict[str, Any]) -> bool:
        """
        Run gRINN analysis in Docker container.
        
        Args:
            input_dir: Directory containing input files
            output_dir: Directory to store results
            job_params: Job parameters for gRINN
            
        Returns:
            True if analysis completed successfully
        """
        try:
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Build Docker command
            docker_cmd = [
                'docker', 'run',
                '--rm',  # Remove container after execution
                '-v', f'{input_dir}:/input:ro',  # Mount input directory as read-only
                '-v', f'{output_dir}:/output',   # Mount output directory
                '--memory=8g',  # Memory limit
                '--cpus=4',     # CPU limit
                self.docker_image
            ]
            
            # Add gRINN parameters
            grinn_args = self._build_grinn_args(job_params)
            docker_cmd.extend(grinn_args)
            
            logger.info(f"Starting Docker container: {' '.join(docker_cmd)}")
            
            # Execute Docker container
            process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Monitor process output
            output_lines = []
            error_lines = []
            
            while True:
                stdout_line = process.stdout.readline()
                stderr_line = process.stderr.readline()
                
                if stdout_line:
                    output_lines.append(stdout_line.strip())
                    logger.debug(f"Docker stdout: {stdout_line.strip()}")
                
                if stderr_line:
                    error_lines.append(stderr_line.strip())
                    logger.debug(f"Docker stderr: {stderr_line.strip()}")
                
                # Check if process finished
                if process.poll() is not None:
                    break
                
                # Check timeout
                if time.time() - process.returncode > self.timeout:
                    process.kill()
                    logger.error("Docker process timed out")
                    return False
            
            # Get final return code
            return_code = process.poll()
            
            if return_code == 0:
                logger.info("gRINN analysis completed successfully")
                return True
            else:
                logger.error(f"gRINN analysis failed with return code {return_code}")
                logger.error(f"Error output: {error_lines}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to run gRINN analysis: {e}")
            return False
    
    def _build_grinn_args(self, job_params: Dict[str, Any]) -> list:
        """Build gRINN command line arguments from job parameters."""
        args = [
            'python', '/grinn/grinn_workflow.py',
            '--input-dir', '/input',
            '--output-dir', '/output'
        ]
        
        # Add parameters
        if 'simulation_time_ns' in job_params:
            args.extend(['--simulation-time', str(job_params['simulation_time_ns'])])
        
        if 'temperature_k' in job_params:
            args.extend(['--temperature', str(job_params['temperature_k'])])
        
        if 'energy_cutoff' in job_params:
            args.extend(['--energy-cutoff', str(job_params['energy_cutoff'])])
        
        if 'distance_cutoff_nm' in job_params:
            args.extend(['--distance-cutoff', str(job_params['distance_cutoff_nm'])])
        
        if 'network_threshold' in job_params:
            args.extend(['--network-threshold', str(job_params['network_threshold'])])
        
        if job_params.get('include_backbone', True):
            args.append('--include-backbone')
        
        if job_params.get('generate_plots', True):
            args.append('--generate-plots')
        
        if job_params.get('generate_network', True):
            args.append('--generate-network')
        
        # Add interaction types
        interaction_types = job_params.get('interaction_types', ['total'])
        for itype in interaction_types:
            args.extend(['--interaction-type', itype])
        
        return args


@app.task(bind=True, name='grinn_web.process_grinn_job')
def process_grinn_job(self, job_id: str):
    """
    Celery task to process a gRINN job.
    
    Args:
        job_id: Unique job identifier
    """
    logger.info(f"Starting processing of job {job_id}")
    
    # Get job queue and storage managers
    queue_manager = get_queue_manager()
    storage_manager = get_storage_manager()
    
    # Temporary directories
    temp_input_dir = None
    temp_output_dir = None
    
    try:
        # Get job from queue
        job = queue_manager.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        # Update status to running
        queue_manager.update_job_status(
            job_id, 
            JobStatus.RUNNING, 
            "Downloading input files",
            progress=10,
            current_step="Downloading input files from cloud storage"
        )
        
        # Create temporary directories
        temp_input_dir = tempfile.mkdtemp(prefix=f"grinn_input_{job_id}_")
        temp_output_dir = tempfile.mkdtemp(prefix=f"grinn_output_{job_id}_")
        
        logger.info(f"Created temp directories: input={temp_input_dir}, output={temp_output_dir}")
        
        # Download input files from GCS
        try:
            file_paths = storage_manager.download_job_inputs(job_id, temp_input_dir)
            logger.info(f"Downloaded {len(file_paths)} input files for job {job_id}")
        except Exception as e:
            queue_manager.update_job_status(
                job_id,
                JobStatus.FAILED,
                f"Failed to download input files: {str(e)}"
            )
            return {'status': 'failed', 'error': str(e)}
        
        # Validate input files
        queue_manager.update_job_status(
            job_id,
            JobStatus.RUNNING,
            "Validating input files",
            progress=20,
            current_step="Validating input file format and structure"
        )
        
        required_files = ['pdb', 'xtc']  # Minimum required files
        available_types = set()
        
        for filename in file_paths.keys():
            extension = filename.lower().split('.')[-1] if '.' in filename else ''
            available_types.add(extension)
        
        missing_types = set(required_files) - available_types
        if missing_types:
            error_msg = f"Missing required file types: {', '.join(missing_types)}"
            queue_manager.update_job_status(job_id, JobStatus.FAILED, error_msg)
            return {'status': 'failed', 'error': error_msg}
        
        # Initialize Docker runner
        docker_runner = GrinnDockerRunner()
        
        # Run gRINN analysis
        queue_manager.update_job_status(
            job_id,
            JobStatus.RUNNING,
            "Running gRINN analysis",
            progress=30,
            current_step="Executing molecular dynamics analysis in Docker container"
        )
        
        # Get job parameters
        job_params = job.parameters.to_dict() if job.parameters else {}
        
        success = docker_runner.run_grinn_analysis(
            temp_input_dir,
            temp_output_dir,
            job_params
        )
        
        if not success:
            queue_manager.update_job_status(
                job_id,
                JobStatus.FAILED,
                "gRINN analysis failed"
            )
            return {'status': 'failed', 'error': 'gRINN analysis failed'}
        
        # Upload results
        queue_manager.update_job_status(
            job_id,
            JobStatus.RUNNING,
            "Uploading results",
            progress=80,
            current_step="Uploading analysis results to cloud storage"
        )
        
        try:
            results_gcs_path = storage_manager.upload_job_results(job_id, temp_output_dir)
            logger.info(f"Uploaded results for job {job_id} to {results_gcs_path}")
        except Exception as e:
            queue_manager.update_job_status(
                job_id,
                JobStatus.FAILED,
                f"Failed to upload results: {str(e)}"
            )
            return {'status': 'failed', 'error': str(e)}
        
        # Update job with results path
        job.results_gcs_path = results_gcs_path
        queue_manager.store_job(job)
        
        # Mark job as completed
        queue_manager.update_job_status(
            job_id,
            JobStatus.COMPLETED,
            "Analysis completed successfully",
            progress=100,
            current_step="Job completed"
        )
        
        logger.info(f"Successfully completed job {job_id}")
        
        return {
            'status': 'completed',
            'job_id': job_id,
            'results_gcs_path': results_gcs_path,
            'completion_time': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {e}")
        
        # Update job status to failed
        queue_manager.update_job_status(
            job_id,
            JobStatus.FAILED,
            f"Job processing failed: {str(e)}"
        )
        
        return {'status': 'failed', 'error': str(e)}
        
    finally:
        # Cleanup temporary directories
        try:
            if temp_input_dir and os.path.exists(temp_input_dir):
                shutil.rmtree(temp_input_dir)
                logger.debug(f"Cleaned up temp input directory: {temp_input_dir}")
            
            if temp_output_dir and os.path.exists(temp_output_dir):
                shutil.rmtree(temp_output_dir)
                logger.debug(f"Cleaned up temp output directory: {temp_output_dir}")
                
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directories: {e}")


@app.task(name='grinn_web.cleanup_old_jobs')
def cleanup_old_jobs():
    """Periodic task to clean up old jobs."""
    logger.info("Starting cleanup of old jobs")
    try:
        queue_manager = get_queue_manager()
        queue_manager.cleanup_old_jobs()
        logger.info("Completed cleanup of old jobs")
    except Exception as e:
        logger.error(f"Failed to cleanup old jobs: {e}")


@app.task(name='grinn_web.health_check')
def health_check():
    """Health check task for monitoring worker status."""
    return {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'worker_id': os.getenv('WORKER_ID', 'unknown')
    }


if __name__ == '__main__':
    # Start Celery worker
    logger.info("Starting Celery worker for gRINN job processing")
    app.worker_main(['worker', '--loglevel=info', '--queues=grinn_jobs'])