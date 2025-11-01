"""
Celery tasks for gRINN Web Service
Handles computational job processing using Docker containers
"""

import os
import sys
import docker
import tempfile
import shutil
import zipfile
from celery import Celery
from typing import Dict, Any
import logging

# Add parent directory to path for Celery workers to find shared modules
project_root = os.path.dirname(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.database import DatabaseManager, JobModel
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
        # For mock storage (local dev), use storage location directly to avoid /tmp issue with Docker in WSL2
        # For cloud storage, download to temp directory
        use_temp_dir = not hasattr(local_storage_manager, 'base_dir')
        
        if use_temp_dir:
            temp_dir = tempfile.mkdtemp()
            input_dir = os.path.join(temp_dir, 'input')
            output_dir = os.path.join(temp_dir, 'output')
            os.makedirs(input_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)
        else:
            # Mock storage - use storage location directly (accessible to Docker)
            base_storage_dir = local_storage_manager.base_dir
            input_dir = os.path.join(base_storage_dir, job_id, 'input')
            output_dir = os.path.join(base_storage_dir, job_id, 'output')
            os.makedirs(output_dir, exist_ok=True)
        
        try:
            # Download input files from storage (for cloud) or verify they exist (for mock)
            logger.info(f"Downloading input files for job {job_id}")
            
            # Get job details to determine input mode and files
            job = local_db_manager.get_job(job_id)
            input_mode = job_params.get('input_mode', 'trajectory')
            
            # Download all input files for the job
            if use_temp_dir:
                file_paths = local_storage_manager.download_job_inputs(job_id, input_dir)
            else:
                # For mock storage, files are already in place
                file_paths = {}
                if os.path.exists(input_dir):
                    for filename in os.listdir(input_dir):
                        file_path = os.path.join(input_dir, filename)
                        if os.path.isfile(file_path):
                            file_paths[filename] = file_path
                logger.info(f"Using {len(file_paths)} input files from mock storage at {input_dir}")
            
            # Extract any ZIP files directly in the input directory (before Docker)
            logger.info(f"Checking for ZIP files to extract in {input_dir}")
            zip_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.zip')]
            
            for zip_filename in zip_files:
                zip_path = os.path.join(input_dir, zip_filename)
                logger.info(f"Extracting ZIP file: {zip_filename}")
                
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        # Extract all files preserving directory structure
                        zip_ref.extractall(input_dir)
                        extracted_files = zip_ref.namelist()
                        logger.info(f"Extracted {len(extracted_files)} files from {zip_filename}:")
                        for extracted_file in extracted_files:
                            if not extracted_file.endswith('/'):  # Skip directory entries
                                logger.info(f"  - {extracted_file}")
                except zipfile.BadZipFile as e:
                    logger.error(f"Failed to extract {zip_filename}: not a valid ZIP file - {e}")
                except Exception as e:
                    logger.error(f"Failed to extract {zip_filename}: {e}")
            
            # Analyze downloaded files to determine structure, topology, and trajectory
            input_files = job.input_files or []
            structure_file = None
            topology_file = None
            trajectory_file = None
            
            for file_info in input_files:
                filename = file_info['filename']
                file_type = file_info['file_type']
                
                logger.info(f"Found {filename} ({file_type})")
                
                # Track file paths by type
                if file_type in ['pdb', 'gro']:
                    structure_file = filename
                elif file_type == 'top':
                    topology_file = filename
                elif file_type in ['xtc', 'trr']:
                    trajectory_file = filename
            
            if not structure_file:
                raise ValueError(f"No structure file found for job {job_id}")
            
            # Run gRINN analysis in Docker container
            logger.info(f"Running gRINN analysis for job {job_id} in {input_mode} mode")
            docker_client = docker.from_env()
            
            grinn_image = os.getenv('GRINN_DOCKER_IMAGE', 'grinn:latest')
            
            # Build Docker command following grinn_workflow.py argument structure
            # The Docker entrypoint expects 'workflow' as the first argument,
            # then it internally calls: conda run -n grinn-env python -u grinn_workflow.py [args]
            # Positional arguments: structure_file out_folder
            docker_command = [
                'workflow',                   # Docker entrypoint mode
                f'/input/{structure_file}',  # structure_file (positional)
                '/output'                     # out_folder (positional)
            ]
            
            # Input mode specific arguments
            if input_mode == 'ensemble':
                # Ensemble mode: multi-model PDB, topology will be generated
                docker_command.append('--ensemble_mode')
                
                # Force field for topology recreation (if specified)
                force_field = job_params.get('force_field', 'amber99sb-ildn')
                docker_command.extend(['--force_field', force_field])
                
                # Optional water model
                water_model = job_params.get('water_model', 'tip3p')
                docker_command.extend(['--water_model', water_model])
                
            else:
                # Trajectory mode: requires topology and trajectory files
                if not topology_file:
                    raise ValueError(f"Topology file required for trajectory mode")
                if not trajectory_file:
                    raise ValueError(f"Trajectory file required for trajectory mode")
                
                docker_command.extend(['--top', f'/input/{topology_file}'])
                docker_command.extend(['--traj', f'/input/{trajectory_file}'])
            
            # Common optional parameters
            
            # Initial pair filter cutoff (default: 10.0)
            if job_params.get('initpairfilter_cutoff'):
                docker_command.extend(['--initpairfiltercutoff', str(job_params['initpairfilter_cutoff'])])
            
            # Skip frames in trajectory (default: 1 = no skipping)
            if job_params.get('skip_frames') and job_params['skip_frames'] > 1:
                docker_command.extend(['--skip', str(job_params['skip_frames'])])
            
            # Source and target selection for residue filtering
            if job_params.get('source_sel'):
                # source_sel is a list of residue IDs/names
                source_sel = job_params['source_sel']
                if isinstance(source_sel, str):
                    source_sel = source_sel.split()
                docker_command.extend(['--source_sel'] + source_sel)
            
            if job_params.get('target_sel'):
                # target_sel is a list of residue IDs/names
                target_sel = job_params['target_sel']
                if isinstance(target_sel, str):
                    target_sel = target_sel.split()
                docker_command.extend(['--target_sel'] + target_sel)
            
            # Number of threads (default: 4)
            nt = job_params.get('nt', 4)  # Default to 4 threads
            docker_command.extend(['--nt', str(nt)])
            
            # GPU acceleration flag
            if job_params.get('use_gpu'):
                docker_command.append('--gpu')
            
            # PDB fixer flag (default: fix PDB)
            if job_params.get('skip_pdb_fix'):
                docker_command.append('--nofixpdb')
            
            # PEN (Protein Energy Network) creation
            if job_params.get('create_pen'):
                docker_command.append('--create_pen')
                
                # PEN cutoffs (list of energy cutoff values)
                if job_params.get('pen_cutoffs'):
                    cutoffs = job_params['pen_cutoffs']
                    if isinstance(cutoffs, (list, tuple)):
                        docker_command.extend(['--pen_cutoffs'] + [str(c) for c in cutoffs])
                
                # Include covalent bonds in PEN
                if job_params.get('pen_include_covalents') is not None:
                    include_cov = job_params['pen_include_covalents']
                    if isinstance(include_cov, (list, tuple)):
                        docker_command.extend(['--pen_include_covalents'] + [str(ic).lower() for ic in include_cov])
            
            logger.info(f"Docker command: {' '.join(docker_command)}")
            logger.info(f"Mounting host directory {input_dir} to container /input")
            
            # List all files and directories in input_dir for debugging
            if os.path.exists(input_dir):
                all_items = []
                for root, dirs, files in os.walk(input_dir):
                    rel_root = os.path.relpath(root, input_dir)
                    if rel_root != '.':
                        all_items.append(f"  DIR: {rel_root}/")
                    for file in files:
                        rel_path = os.path.join(rel_root, file) if rel_root != '.' else file
                        all_items.append(f"  FILE: {rel_path}")
                logger.info(f"Input directory structure:\n" + "\n".join(all_items))
            else:
                logger.error(f"Input directory does not exist: {input_dir}")
            
            # Run container in detached mode with a name for log streaming
            container_name = f"grinn-{job_id}"
            logger.info(f"Starting container {container_name} with command: {' '.join(docker_command)}")
            
            container = docker_client.containers.run(
                grinn_image,
                command=docker_command,
                volumes={
                    input_dir: {'bind': '/input', 'mode': 'ro'},
                    output_dir: {'bind': '/output', 'mode': 'rw'}
                },
                name=container_name,
                remove=False,  # Don't auto-remove so we can get logs
                detach=True,   # Run in background
                stdout=True,
                stderr=True
            )
            
            logger.info(f"Container {container_name} started, waiting for completion...")
            
            # Wait for container to finish and get exit code
            result = container.wait()
            exit_code = result.get('StatusCode', -1)
            
            # Get container logs (but keep container for a while for log viewing)
            logs = container.logs(stdout=True, stderr=True).decode('utf-8', errors='replace')
            logger.info(f"Container output for job {job_id} (exit code: {exit_code}):\n{logs}")
            
            # Check if container exited successfully
            if exit_code != 0:
                # Keep failed container for debugging
                logger.error(f"Container {container_name} failed with exit code {exit_code}. Keeping container for log inspection.")
                raise RuntimeError(f"Container exited with code {exit_code}. Check logs for details.")
            
            # For successful jobs, schedule container cleanup after 1 hour
            # This allows users to view logs while keeping system clean
            # Note: Container will be removed by Docker's built-in cleanup or manually
            logger.info(f"Container {container_name} completed successfully. Keeping container for log access (will be cleaned up later).")
            
            # Upload results to storage
            logger.info(f"Uploading results for job {job_id}")
            
            # Upload entire results directory to GCS
            results_gcs_prefix = local_storage_manager.upload_job_results(job_id, output_dir)
            
            # Get list of uploaded result files for job metadata
            result_files = []
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, output_dir)
                    storage_path = f"{results_gcs_prefix}{relative_path}"
                    result_files.append(storage_path)
            
            # TODO: Add optional cleanup of input files to save storage costs
            # For now, keeping input files for debugging and reprocessing capabilities
            
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
            local_db_manager.update_job_status(
                job_id,
                JobStatus.FAILED,
                current_step="Job failed",
                error_message=str(e)
            )
            
            raise
        
        finally:
            # Cleanup temp directory if we created one
            if use_temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
    
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
        
        # Get old jobs (older than 7 days) and clean them up
        deleted_count = local_db_manager.cleanup_old_jobs(days_old=7)
        logger.info(f"Cleaned up {deleted_count} old jobs")
            
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