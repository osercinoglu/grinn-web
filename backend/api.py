"""
REST API backend for gRINN Web Service.
Provides endpoints for job management and status monitoring using Celery.
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS
from celery.result import AsyncResult

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Add parent directory to path for shared modules
project_root = os.path.dirname(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.models import Job, JobStatus, JobParameters, FileType, JobFile, JobSubmissionRequest
from shared.config import get_config, setup_logging
from shared.storage import get_storage_manager
from shared.database import DatabaseManager, JobModel, JobStatus as DBJobStatus

# Import Celery tasks
try:
    from backend.tasks import process_grinn_job
except ImportError:
    # Handle import error gracefully for development
    process_grinn_job = None
    logger = logging.getLogger(__name__)
    logger.warning("Could not import process_grinn_job - task submission will fail")

# Import dashboard manager
from backend.dashboard_manager import DashboardManager

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Get configuration
config = get_config()

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend communication

# Global managers
storage_manager = None
database_manager = None
dashboard_manager = None
_managers_initialized = False

def initialize_managers():
    """Initialize storage and database managers."""
    global storage_manager, database_manager, dashboard_manager, _managers_initialized
    
    if _managers_initialized:
        return True
        
    try:
        storage_manager = get_storage_manager()
        database_manager = DatabaseManager()
        
        # Initialize database if needed
        database_manager.init_db()
        
        # Initialize dashboard manager with public host from config
        dashboard_manager = DashboardManager(
            storage_manager,
            public_host=config.dashboard_public_host
        )
        
        _managers_initialized = True
        logger.info("Managers initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize managers: {e}")
        return False

def ensure_managers_initialized():
    """Ensure managers are initialized before handling requests."""
    if not _managers_initialized:
        if not initialize_managers():
            raise RuntimeError("Failed to initialize managers")

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0'
    })

# NOTE: Legacy POST /api/jobs endpoint removed.
# Job submission now uses signed URL workflow:
# 1. POST /api/generate-upload-urls - creates job, returns signed URLs
# 2. Frontend uploads files directly to GCS using signed URLs
# 3. POST /api/jobs/<job_id>/confirm-uploads - verifies uploads and starts processing
# This eliminates file transfer through backend, reducing bandwidth and improving scalability.

# Old get_all_jobs function removed - replaced by get_jobs function

@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id: str):
    """Get detailed job information."""
    try:
        ensure_managers_initialized()
        job = database_manager.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        job_data = {
            'job_id': job.id,
            'job_name': job.job_name,
            'description': job.description,
            'status': job.status,  # Already a string value
            'current_step': job.current_step,
            'progress_percentage': job.progress_percentage or 0,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'updated_at': (job.completed_at or job.started_at or job.created_at).isoformat() if (job.completed_at or job.started_at or job.created_at) else None,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'user_email': job.user_email,
            'parameters': job.parameters,
            'input_files': job.input_files,
            'results_gcs_path': job.results_gcs_path,
            'error_message': job.error_message,
            'worker_id': job.worker_id
        }
        
        return jsonify(job_data)
        
    except Exception as e:
        logger.error(f"Error getting job {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/status', methods=['GET'])
def get_job_status(job_id: str):
    """Get job status and progress."""
    try:
        ensure_managers_initialized()
        job = database_manager.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        # If job has a Celery task ID, get additional info from Celery
        celery_info = {}
        if job.worker_id:
            try:
                from tasks import celery_app
                result = AsyncResult(job.worker_id, app=celery_app)
                celery_info = {
                    'celery_status': result.status,
                    'celery_info': result.info if result.info else {}
                }
            except Exception as e:
                logger.warning(f"Could not get Celery info for task {job.worker_id}: {e}")
        
        return jsonify({
            'job_id': job.id,
            'status': job.status,  # Already a string value
            'current_step': job.current_step,
            'progress_percentage': job.progress_percentage or 0,
            'error_message': job.error_message,
            'updated_at': (job.completed_at or job.started_at or job.created_at).isoformat() if (job.completed_at or job.started_at or job.created_at) else None,
            **celery_info
        })
        
    except Exception as e:
        logger.error(f"Error getting job status for {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id: str):
    """Cancel a job."""
    try:
        ensure_managers_initialized()
        job = database_manager.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        # Cancel Celery task if it exists
            if job.worker_id:
                try:
                    from tasks import celery_app
                    celery_app.control.revoke(job.worker_id, terminate=True)
                    logger.info(f"Cancelled Celery task {job.worker_id}")
                except Exception as e:
                    logger.error(f"Error cancelling Celery task: {e}")
            
            # Update job status
            database_manager.update_job_status(
                job_id,
                DBJobStatus.CANCELLED,
                current_step="Job cancelled by user"
            )
        
        return jsonify({
            'success': True,
            'message': 'Job cancelled successfully'
        })
        
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

# Second duplicate get_all_jobs function removed - replaced by get_jobs function

@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    """Get all jobs with optional status filtering. Private jobs are excluded from public queue."""
    try:
        ensure_managers_initialized()
        status_filter = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        with database_manager.get_session() as session:
            query = session.query(JobModel)
            
            # Filter out private jobs from public queue
            query = query.filter(JobModel.is_private == False)
            
            # Apply status filter if provided
            if status_filter and status_filter != 'all':
                query = query.filter(JobModel.status == status_filter)
            
            # Order by creation time (newest first)
            query = query.order_by(JobModel.created_at.desc())
            
            # Apply pagination
            query = query.offset(offset).limit(limit)
            
            jobs = query.all()
            
            # Convert to dict format
            jobs_data = [job.to_dict() for job in jobs]
        
        return jsonify({
            'success': True,
            'jobs': jobs_data,
            'total': len(jobs_data),
            'offset': offset,
            'limit': limit
        })
        
    except Exception as e:
        logger.error(f"Error getting jobs: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/generate-upload-urls', methods=['POST'])
def generate_upload_urls():
    """
    Generate signed URLs for direct file uploads to GCS.
    This allows frontend to upload files directly to cloud storage without passing through backend.
    """
    try:
        ensure_managers_initialized()
        data = request.get_json()
        
        # Validate required fields
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
            
        if not data.get('files'):
            return jsonify({'error': 'files list is required'}), 400
        
        files_info = data['files']
        if not isinstance(files_info, list):
            return jsonify({'error': 'files must be a list'}), 400
            
        # Validate each file entry
        for i, file_info in enumerate(files_info):
            if not isinstance(file_info, dict):
                return jsonify({'error': f'File entry {i} must be an object'}), 400
            if not file_info.get('filename'):
                return jsonify({'error': f'File entry {i} missing filename'}), 400
            if not file_info.get('content_type'):
                return jsonify({'error': f'File entry {i} missing content_type'}), 400
        
        files_info = data['files']
        input_mode = data.get('input_mode', 'trajectory')
        force_field = data.get('force_field')
        parameters = data.get('parameters', {})
        is_private = data.get('is_private', False)
        job_name = data.get('job_name')  # Optional user-provided name
        
        # Create job in database with status 'pending_upload'
        mode_desc = 'Ensemble' if input_mode == 'ensemble' else 'Trajectory'
        with database_manager.get_session() as session:
            job_model = JobModel(
                job_name=job_name,  # Can be None
                description=data.get('description', f'{mode_desc} analysis using gRINN'),
                user_email=data.get('user_email'),
                is_private=is_private,
                parameters=parameters,
                input_files=[{
                    'filename': f['filename'],
                    'file_type': f.get('file_type', 'unknown'),
                    'size_bytes': f.get('size', 0)
                } for f in files_info]
            )
            session.add(job_model)
            session.commit()
            job_id = job_model.id
        
        logger.info(f"Created job {job_id} for signed URL upload")
        
        # Update status to pending_upload
        database_manager.update_job_status(
            job_id,
            DBJobStatus.PENDING,
            current_step="Waiting for file uploads",
            progress_percentage=0
        )
        
        # Generate signed URLs for each file
        try:
            # Validate storage manager interface before using
            if not hasattr(storage_manager, 'generate_multiple_signed_upload_urls'):
                logger.error("Storage manager missing generate_multiple_signed_upload_urls method")
                return jsonify({'error': 'Storage configuration error'}), 500
                
            upload_urls = storage_manager.generate_multiple_signed_upload_urls(
                job_id=job_id,
                files_info=files_info,
                expiration_minutes=60  # URLs valid for 1 hour
            )
            
            if not upload_urls:
                logger.error(f"No upload URLs generated for job {job_id}")
                return jsonify({'error': 'Failed to generate upload URLs'}), 500
            
            logger.info(f"Generated {len(upload_urls)} signed upload URLs for job {job_id}")
            
            return jsonify({
                'success': True,
                'job_id': job_id,
                'upload_urls': upload_urls,
                'expires_at': upload_urls[0].get('expires_at') if upload_urls else None,
                'message': 'Upload URLs generated successfully'
            })
            
        except TypeError as e:
            logger.error(f"Storage manager method signature error for job {job_id}: {e}")
            # Update job status to failed
            database_manager.update_job_status(
                job_id,
                DBJobStatus.FAILED,
                current_step="Failed to generate upload URLs",
                error_message=f"Storage interface error: {str(e)}"
            )
            return jsonify({'error': 'Storage interface error - check method signatures'}), 500
            
        except Exception as e:
            logger.error(f"Failed to generate upload URLs for job {job_id}: {e}")
            # Update job status to failed
            database_manager.update_job_status(
                job_id,
                DBJobStatus.FAILED,
                current_step="Failed to generate upload URLs", 
                error_message=str(e)
            )
            return jsonify({'error': f'Failed to generate upload URLs: {str(e)}'}), 500
            
        except Exception as e:
            # Clean up job if URL generation fails
            database_manager.update_job_status(
                job_id,
                DBJobStatus.FAILED,
                current_step="Failed to generate upload URLs",
                error_message=str(e)
            )
            raise
        
    except Exception as e:
        logger.error(f"Error generating upload URLs: {e}")
        return jsonify({'error': f'Failed to generate upload URLs: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/confirm-uploads', methods=['POST'])
def confirm_uploads(job_id: str):
    """
    Confirm that all files have been uploaded and start processing.
    This is called after frontend completes direct uploads to GCS.
    """
    try:
        ensure_managers_initialized()
        
        # Get job from database and check status within session context
        job_status = None
        with database_manager.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return jsonify({'error': 'Job not found'}), 404
            
            job_status = job.status
        
        # Check job is in the right state
        if job_status not in [DBJobStatus.PENDING, DBJobStatus.UPLOADING]:
            return jsonify({
                'error': f'Job is in {job_status.value} state, cannot confirm uploads'
            }), 400
        
        data = request.get_json()
        logger.info(f"Received confirm-uploads request data: {data}")
        uploaded_files = data.get('uploaded_files', [])
        logger.info(f"Extracted uploaded_files: {uploaded_files}")
        
        if not uploaded_files:
            return jsonify({'error': 'uploaded_files list is required'}), 400
        
        # Verify all files were actually uploaded to GCS
        all_verified = True
        for file_info in uploaded_files:
            file_path = file_info.get('file_path')
            if not file_path:
                continue
            
            if not storage_manager.verify_file_uploaded(file_path):
                logger.error(f"File not found in GCS: {file_path}")
                all_verified = False
                break
        
        if not all_verified:
            database_manager.update_job_status(
                job_id,
                DBJobStatus.FAILED,
                current_step="File verification failed",
                error_message="Not all files were successfully uploaded to cloud storage"
            )
            return jsonify({
                'error': 'File verification failed - not all files found in storage'
            }), 400
        
        logger.info(f"Verified all {len(uploaded_files)} files uploaded for job {job_id}")
        
        # Update job status to queued
        database_manager.update_job_status(
            job_id,
            DBJobStatus.QUEUED,
            current_step="Job queued for processing",
            progress_percentage=20
        )
        
        # Submit job to Celery processing queue
        try:
            if process_grinn_job is None:
                raise ImportError("process_grinn_job task not available")
            
            # Get parameters from job within session context
            parameters = {}
            with database_manager.get_session() as session:
                job_model = session.query(JobModel).filter(JobModel.id == job_id).first()
                if job_model:
                    parameters = job_model.parameters or {}
            
            # Submit task to Celery
            task = process_grinn_job.delay(job_id, parameters)
            
            # Update job with Celery task ID using existing method
            database_manager.set_worker_info(job_id, task.id)
            
            # Update job status to indicate processing started
            database_manager.update_job_status(
                job_id,
                DBJobStatus.QUEUED,
                current_step="Processing started",
                progress_percentage=25
            )
            
            logger.info(f"Submitted job {job_id} with Celery task ID {task.id}")
            
            return jsonify({
                'success': True,
                'job_id': job_id,
                'status': DBJobStatus.QUEUED.value,
                'message': 'Files verified and processing started',
                'monitor_url': f'/monitor/{job_id}'
            }), 200
            
        except Exception as e:
            database_manager.update_job_status(
                job_id,
                DBJobStatus.FAILED,
                current_step="Failed to queue job",
                error_message=f"Queue submission error: {str(e)}"
            )
            return jsonify({'error': f'Failed to queue job: {str(e)}'}), 500
        
    except Exception as e:
        logger.error(f"Error confirming uploads for job {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get system statistics."""
    try:
        ensure_managers_initialized()
        with database_manager.get_session() as session:
            stats = database_manager.get_job_statistics(session)
        
        # Get Celery queue stats
        celery_stats = {}
        try:
            from tasks import celery_app
            inspect = celery_app.control.inspect()
            celery_stats = {
                'active_tasks': len(inspect.active() or {}),
                'scheduled_tasks': len(inspect.scheduled() or {}),
                'reserved_tasks': len(inspect.reserved() or {})
            }
        except Exception as e:
            logger.warning(f"Could not get Celery stats: {e}")
        
        return jsonify({
            **stats,
            **celery_stats,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

# Initialize managers when module is imported (for non-main execution)
if not _managers_initialized:
    try:
        initialize_managers()
    except Exception as e:
        logger.warning(f"Failed to initialize managers on import: {e}")
        # Managers will be initialized on first request via ensure_managers_initialized()


# ============================================================================
# Dashboard Management Endpoints
# ============================================================================

@app.route('/api/jobs/<job_id>/dashboard/start', methods=['POST'])
def start_dashboard(job_id):
    """
    Start a dashboard container for a job.
    
    Returns:
        JSON with dashboard URL and port
    """
    ensure_managers_initialized()
    
    try:
        # Verify job exists
        job = database_manager.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        # Start dashboard
        result = dashboard_manager.start_dashboard(job_id)
        
        if result['success']:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error starting dashboard for {job_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs/<job_id>/dashboard/stop', methods=['POST'])
def stop_dashboard(job_id):
    """
    Stop a dashboard container for a job.
    
    Returns:
        JSON with success status
    """
    ensure_managers_initialized()
    
    try:
        result = dashboard_manager.stop_dashboard(job_id)
        
        if result['success']:
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Error stopping dashboard for {job_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs/<job_id>/dashboard/status', methods=['GET'])
def dashboard_status(job_id):
    """
    Get dashboard status for a job.
    
    Returns:
        JSON with dashboard running status and info
    """
    ensure_managers_initialized()
    
    try:
        status = dashboard_manager.get_dashboard_status(job_id)
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard status for {job_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs/<job_id>/dashboard/logs', methods=['GET'])
def dashboard_logs(job_id):
    """
    Get dashboard container logs for a job.
    
    Query Parameters:
        since: Optional timestamp to get logs since
    
    Returns:
        JSON with container logs
    """
    ensure_managers_initialized()
    
    try:
        since_timestamp = request.args.get('since')
        logs = dashboard_manager.get_dashboard_logs(job_id, since_timestamp)
        return jsonify(logs), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard logs for {job_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/dashboards', methods=['GET'])
def list_dashboards():
    """
    List all active dashboard instances.
    
    Returns:
        JSON with list of active dashboards
    """
    ensure_managers_initialized()
    
    try:
        active = dashboard_manager.list_active_dashboards()
        return jsonify({'dashboards': active}), 200
        
    except Exception as e:
        logger.error(f"Error listing dashboards: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs/<job_id>/logs', methods=['GET'])
def get_job_logs(job_id):
    """
    Get container logs for a running or completed job.
    Attempts to fetch logs from the gRINN processing container.
    
    Query Parameters:
        tail: Number of lines to return from end (default: 100, max: 1000)
        since: Unix timestamp to get logs since
    
    Returns:
        JSON with container logs
    """
    ensure_managers_initialized()
    
    try:
        import docker
        
        # Get tail parameter (default 100, max 1000)
        tail = request.args.get('tail', '100')
        try:
            tail = min(int(tail), 1000)
        except ValueError:
            tail = 100
        
        # Get since parameter
        since_timestamp = request.args.get('since')
        
        # Try to get logs from Docker container
        # Container name pattern: grinn-{job_id}
        docker_client = docker.from_env()
        
        logs_text = ""
        container_found = False
        container_status = "unknown"
        
        # Primary container name pattern (as created in tasks.py)
        container_name = f"grinn-{job_id}"
        
        try:
            # Try to get container (works for both running and stopped)
            container = docker_client.containers.get(container_name)
            container_found = True
            container_status = container.status
            
            # Get logs from the container
            log_kwargs = {'stdout': True, 'stderr': True, 'timestamps': True}
            
            # If container is still running, get all logs for real-time updates
            # If stopped, use tail to limit output
            if container.status == 'running':
                log_kwargs['tail'] = 'all'  # Get all logs for running containers
                logger.info(f"Fetching ALL logs from RUNNING container {container_name}")
            else:
                log_kwargs['tail'] = tail
                logger.info(f"Fetching last {tail} lines from {container.status} container {container_name}")
            
            if since_timestamp:
                log_kwargs['since'] = int(since_timestamp)
            
            try:
                logs_bytes = container.logs(**log_kwargs)
                logs_text = logs_bytes.decode('utf-8', errors='replace')
                
                if logs_text.strip():
                    logger.info(f"Successfully retrieved {len(logs_text)} characters of logs from container {container_name} (status: {container.status})")
                else:
                    logs_text = f"Container {container_name} is {container.status}, but no logs available yet.\nThis is normal if the container just started."
                    logger.info(f"Container {container_name} has no logs yet (status: {container.status})")
                    
            except Exception as e:
                logger.error(f"Error reading logs from container {container_name}: {e}")
                logs_text = f"Container {container_name} found ({container.status}), but could not read logs: {str(e)}"
                
        except docker.errors.NotFound:
            # Container not found - might be removed or not started yet
            logger.info(f"Container {container_name} not found")
            
            # Try to find any container with job_id in the name
            try:
                all_containers = docker_client.containers.list(
                    all=True, 
                    filters={'name': job_id}
                )
                
                if all_containers:
                    # Found a container with job_id in name
                    container = all_containers[0]
                    container_found = True
                    container_status = container.status
                    
                    log_kwargs = {'tail': tail, 'stdout': True, 'stderr': True}
                    if since_timestamp:
                        log_kwargs['since'] = int(since_timestamp)
                    
                    logs_bytes = container.logs(**log_kwargs)
                    logs_text = logs_bytes.decode('utf-8', errors='replace')
                    logger.info(f"Found alternative container: {container.name}")
            except Exception as e:
                logger.warning(f"Error searching for alternative containers: {e}")
        
        except Exception as e:
            logger.error(f"Error accessing container {container_name}: {e}")
            logs_text = f"Error accessing container: {str(e)}"
        
        # If still no logs, check job status for error messages or current step
        if not logs_text or logs_text.strip() == "":
            job = database_manager.get_job(job_id)
            if job and job.error_message:
                logs_text = f"=== Job Error ===\n{job.error_message}\n\n=== Container Status ===\nContainer not found or no logs available."
            elif job and job.current_step:
                logs_text = f"=== Current Status ===\n{job.current_step}\n\n=== Container Logs ===\nWaiting for container logs...\n\nNote: Logs will appear once the container starts processing.\nIf the job is queued, please wait for it to start."
            else:
                logs_text = "No logs available yet.\n\nPossible reasons:\n- Job is queued and hasn't started\n- Container is starting up\n- Container has been removed after completion"
        
        return jsonify({
            'success': True,
            'logs': logs_text,
            'container_found': container_found,
            'container_status': container_status
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting logs for job {job_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'logs': f"Error retrieving logs: {str(e)}"
        }), 500


if __name__ == '__main__':
    # Initialize managers
    if not initialize_managers():
        logger.error("Failed to initialize managers, exiting")
        exit(1)
    
    # Skip GCS validation in development mode
    development_mode = os.getenv('DEVELOPMENT_MODE', 'false').lower() == 'true'
    if development_mode:
        config.validate(skip_gcs_validation=True)
    else:
        config.validate()
    
    logger.info(f"Starting Backend API server on {config.backend_host}:{config.backend_port}")
    app.run(
        host=config.backend_host,
        port=config.backend_port,
        debug=config.frontend_debug
    )