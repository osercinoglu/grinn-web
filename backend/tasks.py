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
from typing import Dict, Any, Optional
import logging

# Add parent directory to path for Celery workers to find shared modules
project_root = os.path.dirname(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.database import DatabaseManager, JobModel
from shared.models import JobStatus
from shared.local_storage import get_storage_manager, LocalStorageManager
from shared.config import get_config

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

# Get configuration
config = get_config()

# Initialize database and storage
db_manager = DatabaseManager()
storage_manager = get_storage_manager(config.storage_path)

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
    local_config = get_config()
    local_storage_manager = get_storage_manager(local_config.storage_path)

    def _truncate_for_db(text: str, max_chars: int = 20000) -> str:
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return "[...truncated...]\n" + text[-max_chars:]

    def _extract_preflight_summary(preflight_logs: str) -> str:
        """Extract the actionable validation failure from verbose preflight logs."""
        if not preflight_logs:
            return ""

        lines = preflight_logs.splitlines()

        # Prefer the dedicated validation report block emitted by grinn_workflow.py
        report_idx = None
        for i, line in enumerate(lines):
            if "gRINN Input Validation Report" in line:
                report_idx = i
                break

        if report_idx is not None:
            start = report_idx
            # Include the separator line above the title if present
            while start > 0 and lines[start - 1].strip() and set(lines[start - 1].strip()) == {'='}:
                start -= 1

            end = report_idx
            stop_markers = (
                "Workflow cannot proceed",
                "conda.cli.main_run",
                "conda run",
            )
            while end < len(lines) and not any(m in lines[end] for m in stop_markers):
                end += 1
            if end < len(lines) and "Workflow cannot proceed" in lines[end]:
                end += 1

            block = "\n".join(lines[start:end]).strip()
            if block:
                return block

        # Fallback: show the last few ERROR/FAIL lines if the report isn't present
        interesting = []
        for line in lines:
            if line.startswith("ERROR:") or line.startswith("❌") or "Preflight" in line:
                interesting.append(line)
        tail = "\n".join(interesting[-20:]).strip()
        if tail:
            return tail
        return "\n".join(lines[-40:]).strip()

    def _get_existing_error_message() -> Optional[str]:
        try:
            existing_job = local_db_manager.get_job(job_id)
            return existing_job.error_message if existing_job else None
        except Exception:
            return None

    def _update_failed_preserving_error(current_step: str, error_message: Optional[str]):
        existing_error = _get_existing_error_message()
        local_db_manager.update_job_status(
            job_id,
            JobStatus.FAILED,
            current_step=current_step,
            error_message=existing_error or error_message
        )

    try:
        logger.info(f"Starting job {job_id}")

        # Update job status to running
        job = local_db_manager.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        local_db_manager.update_job_status(job_id, JobStatus.RUNNING, "Preparing job", 10)

        # Use local storage directories directly (accessible via NFS for multi-worker setups)
        input_dir = local_storage_manager.get_input_directory(job_id)
        output_dir = local_storage_manager.get_output_directory(job_id)

        try:
            # Verify input files exist
            logger.info(f"Verifying input files for job {job_id}")
            input_mode = job_params.get('input_mode', 'trajectory')
            
            # Files are already in place in local storage (accessible via NFS)
            file_paths = {}
            if os.path.exists(input_dir):
                for filename in os.listdir(input_dir):
                    file_path = os.path.join(input_dir, filename)
                    if os.path.isfile(file_path):
                        file_paths[filename] = file_path
            logger.info(f"Found {len(file_paths)} input files in local storage at {input_dir}")
            
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
            
            # Analyze downloaded files to determine structure, topology, trajectory, and ensemble PDB
            input_files = job.input_files or []
            structure_file = None
            topology_file = None
            trajectory_file = None
            ensemble_pdb_file = None  # For ensemble mode: the multi-model PDB
            
            for file_info in input_files:
                filename = file_info['filename']
                file_type = file_info['file_type']
                file_role = file_info.get('role', 'unknown')
                
                logger.info(f"Found {filename} ({file_type}, role={file_role})")
                
                # Track file paths by role (preferred) or type (fallback)
                if file_role == 'ensemble_pdb':
                    ensemble_pdb_file = filename
                elif file_role == 'structure' or (file_role == 'unknown' and file_type in ['pdb', 'gro']):
                    structure_file = filename
                elif file_role == 'topology' or (file_role == 'unknown' and file_type == 'top'):
                    topology_file = filename
                elif file_role == 'trajectory' or (file_role == 'unknown' and file_type in ['xtc', 'trr']):
                    trajectory_file = filename
            
            # Validate required files based on mode
            if input_mode == 'ensemble':
                if not ensemble_pdb_file:
                    raise ValueError(f"No ensemble PDB file found for job {job_id}. Ensemble mode requires a multi-model PDB file.")
            else:
                if not structure_file:
                    raise ValueError(f"No structure file found for job {job_id}")
            
            # Run gRINN analysis in Docker container
            logger.info(f"Running gRINN analysis for job {job_id} in {input_mode} mode")
            docker_client = docker.from_env()
            
            # Determine GROMACS version from job params (for trajectory mode)
            default_version = os.getenv('GRINN_DOCKER_IMAGE', 'grinn:gromacs-2024.1')
            gromacs_version = job_params.get('gromacs_version')
            
            if gromacs_version:
                grinn_image = f"grinn:gromacs-{gromacs_version}"
                logger.info(f"Using GROMACS version {gromacs_version} for job {job_id}")
            else:
                grinn_image = default_version
                logger.info(f"Using default image {grinn_image} for job {job_id}")
            
            # Validate that the image exists
            try:
                docker_client.images.get(grinn_image)
            except docker.errors.ImageNotFound:
                raise ValueError(f"Docker image '{grinn_image}' not found. Please ensure GROMACS {gromacs_version or 'default'} is available on this worker.")
            
            # Build Docker command following grinn_workflow.py argument structure
            # The Docker entrypoint expects 'workflow' as the first argument,
            # then it internally calls: conda run -n grinn-env python -u grinn_workflow.py [args]
            # Positional arguments: structure_file out_folder
            
            # In ensemble mode, the ensemble PDB is the primary input file
            # In trajectory mode, the structure file is the primary input
            primary_input_file = ensemble_pdb_file if input_mode == 'ensemble' else structure_file
            
            docker_command = [
                'workflow',                         # Docker entrypoint mode
                f'/input/{primary_input_file}',     # structure_file (positional) - ensemble PDB or structure
                '/output'                           # out_folder (positional)
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

            # Maximum frames to process (optional)
            effective_max_frames = job_params.get('max_frames', None)
            if effective_max_frames is None:
                effective_max_frames = getattr(local_config, 'max_frames', None)

            logger.info(
                f"Max frames selection for job {job_id}: job_params.max_frames={job_params.get('max_frames', None)!r}, "
                f"config.MAX_FRAMES={getattr(local_config, 'max_frames', None)!r}"
            )

            if effective_max_frames is not None:
                try:
                    max_frames = int(effective_max_frames)
                    if max_frames > 0:
                        docker_command.extend(['--max_frames', str(max_frames)])
                except (TypeError, ValueError):
                    logger.warning(f"Ignoring invalid max_frames value: {effective_max_frames}")
            
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
            
            # PEN (Protein Energy Network) precompute
            # grinn_workflow.py attempts PEN precompute by default (when eligible).
            # Respect the UI toggle by passing --no_pen when create_pen is explicitly False.
            if job_params.get('create_pen') is False:
                docker_command.append('--no_pen')

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

            # Preflight validation: run workflow in --test-only mode first and surface any errors to the user
            local_db_manager.update_job_status(job_id, JobStatus.RUNNING, "Preflight: validating inputs", 15)

            preflight_container_name = f"grinn-preflight-{job_id}"
            preflight_container = None
            try:
                # Remove any stale container with the same name
                try:
                    stale = docker_client.containers.get(preflight_container_name)
                    stale.remove(force=True)
                except docker.errors.NotFound:
                    pass
                except Exception as cleanup_error:
                    logger.warning(f"Could not remove stale preflight container {preflight_container_name}: {cleanup_error}")

                preflight_command = docker_command + ['--test-only']
                logger.info(
                    f"Starting preflight container {preflight_container_name} with command: {' '.join(preflight_command)}"
                )

                preflight_container = docker_client.containers.run(
                    grinn_image,
                    command=preflight_command,
                    volumes={
                        input_dir: {'bind': '/input', 'mode': 'ro'},
                        output_dir: {'bind': '/output', 'mode': 'rw'}
                    },
                    name=preflight_container_name,
                    user=f'{os.getuid()}:{os.getgid()}',  # Run as host user for correct file ownership
                    remove=False,
                    detach=True,
                    stdout=True,
                    stderr=True
                )

                preflight_result = preflight_container.wait()
                preflight_exit_code = preflight_result.get('StatusCode', -1)
                preflight_logs = preflight_container.logs(stdout=True, stderr=True).decode('utf-8', errors='replace')
                logger.info(
                    f"Preflight output for job {job_id} (exit code: {preflight_exit_code}):\n{preflight_logs}"
                )

                # Persist full preflight logs to output folder for later inspection/download.
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    preflight_log_path = os.path.join(output_dir, 'preflight.log')
                    with open(preflight_log_path, 'w', encoding='utf-8', errors='replace') as f:
                        f.write(preflight_logs)
                except Exception as e:
                    logger.warning(f"Could not write preflight.log for job {job_id}: {e}")

                if preflight_exit_code != 0:
                    summary = _extract_preflight_summary(preflight_logs)
                    error_message = _truncate_for_db(
                        "Preflight validation failed. Please fix the input files/parameters and resubmit.\n\n"
                        + (summary or "(No additional details available.)")
                    )
                    _update_failed_preserving_error("Preflight failed", error_message)
                    raise RuntimeError("Preflight failed")

            finally:
                if preflight_container is not None:
                    try:
                        preflight_container.remove(force=True)
                    except Exception as remove_error:
                        logger.warning(
                            f"Could not remove preflight container {preflight_container_name}: {remove_error}"
                        )

            # Preflight passed; continue with full processing
            local_db_manager.update_job_status(job_id, JobStatus.RUNNING, "Processing gRINN analysis", 25)
            
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
                user=f'{os.getuid()}:{os.getgid()}',  # Run as host user for correct file ownership
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
            
            # Results are already in local storage (output_dir)
            logger.info(f"Job results stored in {output_dir}")
            
            # Update storage metadata for the results
            local_storage_manager.upload_job_results(job_id, output_dir)
            
            # Get list of result files for job metadata
            result_files = []
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, output_dir)
                    result_files.append(relative_path)
            
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
            
            # Update job status to failed (preserve richer error messages if already set)
            _update_failed_preserving_error("Job failed", str(e))
            
            raise
        
        # No temp directory cleanup needed - using local storage directly
    
    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}")
        
        # Update job status to failed
        try:
            _update_failed_preserving_error("Job failed", str(e))
        except Exception as db_error:
            logger.error(f"Failed to update job status: {str(db_error)}")
        
        raise

@celery_app.task
def cleanup_old_jobs():
    """
    Cleanup old jobs and their associated files.
    
    Process:
    1. Delete files for jobs older than JOB_FILE_RETENTION_HOURS
    2. Mark those jobs as EXPIRED (instead of deleting DB records)
    3. Delete EXPIRED job records older than EXPIRED_JOB_RETENTION_DAYS
    """
    # Initialize managers for this worker process
    local_db_manager = DatabaseManager()
    local_config = get_config()
    local_storage_manager = get_storage_manager(local_config.storage_path)
    
    try:
        retention_hours = local_config.job_file_retention_hours
        expired_retention_days = local_config.expired_job_retention_days
        
        logger.info(f"Starting job cleanup (file retention: {retention_hours} hours, expired record retention: {expired_retention_days} days)")
        
        # Step 1: Clean up old job files from storage
        files_cleaned = local_storage_manager.cleanup_old_jobs(retention_hours=retention_hours)
        logger.info(f"Cleaned up files for {files_cleaned} old jobs")
        
        # Step 2: Mark terminal jobs as EXPIRED (files are now deleted)
        expired_count = local_db_manager.mark_jobs_as_expired(hours_old=retention_hours)
        logger.info(f"Marked {expired_count} jobs as expired")
        
        # Step 3: Delete expired job records that are too old
        deleted_count = local_db_manager.delete_expired_jobs(days_old=expired_retention_days)
        logger.info(f"Deleted {deleted_count} old expired job records from database")
            
    except Exception as e:
        logger.error(f"Job cleanup failed: {str(e)}")


@celery_app.task
def cleanup_job_files(job_id: str):
    """
    Cleanup files for a specific job.
    Called when a job is cancelled or needs explicit cleanup.
    
    Args:
        job_id: Job identifier to clean up
    """
    local_config = get_config()
    local_storage_manager = get_storage_manager(local_config.storage_path)
    
    try:
        logger.info(f"Cleaning up files for job {job_id}")
        local_storage_manager.delete_job_files(job_id)
        logger.info(f"Successfully cleaned up files for job {job_id}")
    except Exception as e:
        logger.error(f"Failed to cleanup files for job {job_id}: {str(e)}")


@celery_app.task
def monitor_worker_health():
    """
    Monitor worker health by checking heartbeats.
    Mark workers as offline if they haven't sent heartbeat within timeout.
    Redistribute jobs from offline workers back to the queue.
    """
    local_db_manager = DatabaseManager()
    local_config = get_config()
    
    try:
        timeout_seconds = local_config.worker_heartbeat_timeout_seconds
        
        # Mark workers as offline if no heartbeat
        offline_count = local_db_manager.mark_workers_offline(timeout_seconds=timeout_seconds)
        
        if offline_count > 0:
            logger.warning(f"Marked {offline_count} workers as offline due to missed heartbeats")
            
            # Get all offline workers
            all_workers = local_db_manager.get_all_workers()
            offline_workers = [w for w in all_workers if w.status == 'offline']
            
            # Redistribute jobs from offline workers
            for worker in offline_workers:
                jobs = local_db_manager.get_jobs_by_worker(worker.worker_id)
                
                if jobs:
                    logger.info(f"Redistributing {len(jobs)} jobs from offline worker {worker.worker_id}")
                    
                    for job in jobs:
                        # Reset job to QUEUED status and clear worker_id
                        local_db_manager.update_job_status(
                            job.id,
                            JobStatus.QUEUED,
                            current_step="Requeued due to worker failure"
                        )
                        # Clear worker assignment
                        local_db_manager.set_worker_info(job.id, worker_id=None)
                        # Decrement worker job count
                        local_db_manager.decrement_worker_job_count(worker.worker_id)
                        
                        logger.info(f"Job {job.id} requeued after worker {worker.worker_id} went offline")
        
    except Exception as e:
        logger.error(f"Worker health monitoring failed: {str(e)}")


@celery_app.task
def cleanup_idle_dashboards():
    """
    Clean up idle dashboard containers that haven't received heartbeats.
    Uses the DashboardManager to stop containers that exceed idle timeout.
    """
    try:
        from backend.dashboard_manager import DashboardManager
        from backend.api import storage_manager, dashboard_manager
        
        # Use existing dashboard_manager from API if available, or create one
        if dashboard_manager:
            manager = dashboard_manager
        else:
            local_config = get_config()
            local_storage_manager = get_storage_manager(local_config.storage_path)
            manager = DashboardManager(local_storage_manager)
        
        cleanup_count = manager.cleanup_idle_dashboards()
        
        if cleanup_count > 0:
            logger.info(f"Cleaned up {cleanup_count} idle dashboard containers")
        
    except Exception as e:
        logger.error(f"Dashboard cleanup failed: {str(e)}")


# Periodic task to cleanup old jobs
# Schedule interval is configurable via CLEANUP_INTERVAL_SECONDS (default: 6 hours)
_cleanup_config = get_config()
logger.info(f"Cleanup scheduler configured: interval={_cleanup_config.cleanup_interval_seconds}s, "
            f"file_retention={_cleanup_config.job_file_retention_hours}h, "
            f"expired_retention={_cleanup_config.expired_job_retention_days}d")
logger.info(f"Worker health monitoring: interval=60s, timeout={_cleanup_config.worker_heartbeat_timeout_seconds}s")
logger.info(f"Dashboard cleanup: interval={_cleanup_config.dashboard_cleanup_interval_seconds}s, "
            f"idle_timeout={_cleanup_config.dashboard_idle_timeout_minutes}min")

celery_app.conf.beat_schedule = {
    'cleanup-old-jobs': {
        'task': 'backend.tasks.cleanup_old_jobs',
        'schedule': _cleanup_config.cleanup_interval_seconds,
        'options': {'queue': 'grinn_jobs'},  # Route to queue that workers listen to
    },
    'monitor-worker-health': {
        'task': 'backend.tasks.monitor_worker_health',
        'schedule': 60.0,  # Check every 60 seconds
        'options': {'queue': 'grinn_jobs'},
    },
    'cleanup-idle-dashboards': {
        'task': 'backend.tasks.cleanup_idle_dashboards',
        'schedule': _cleanup_config.dashboard_cleanup_interval_seconds,
        'options': {'queue': 'grinn_jobs'},
    },
}
celery_app.conf.timezone = 'UTC'