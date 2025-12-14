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
from shared.local_storage import get_storage_manager
from shared.worker_registry import WorkerRegistry, get_worker_registry, generate_registration_token
from shared.database import DatabaseManager, JobModel, JobStatus as DBJobStatus
import redis

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
worker_registry = None
redis_client = None
_managers_initialized = False

def initialize_managers():
    """Initialize storage and database managers."""
    global storage_manager, database_manager, dashboard_manager, worker_registry, redis_client, _managers_initialized
    
    if _managers_initialized:
        return True
        
    try:
        # Initialize local storage
        storage_manager = get_storage_manager(config.storage_path)
        database_manager = DatabaseManager()
        
        # Initialize database if needed
        database_manager.init_db()
        
        # Initialize Redis client for worker registry
        redis_client = redis.Redis(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            decode_responses=False
        )
        
        # Initialize worker registry
        worker_registry = get_worker_registry(redis_client)
        
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

# NOTE: Job submission workflow:
# 1. POST /api/jobs - creates job, returns job_id and upload endpoint
# 2. POST /api/jobs/<job_id>/upload - upload files to local storage
# 3. POST /api/jobs/<job_id>/start - starts processing

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
            'results_path': job.results_gcs_path,  # Legacy field name kept for compatibility
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
    """Get all jobs with optional status filtering.

    Private jobs are included for visibility (queue health), but identifying details
    such as job_id are redacted.
    """
    try:
        ensure_managers_initialized()
        status_filter = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        with database_manager.get_session() as session:
            query = session.query(JobModel)

            # NOTE: We intentionally include private jobs so the public queue reflects
            # whether the server is busy/responsive. Identifying details are redacted
            # in the response below.
            
            # Apply status filter if provided
            if status_filter and status_filter != 'all':
                query = query.filter(JobModel.status == status_filter)
            
            # Order by creation time (newest first)
            query = query.order_by(JobModel.created_at.desc())
            
            # Apply pagination
            query = query.offset(offset).limit(limit)
            
            jobs = query.all()

            # Convert to dict format, redacting private job identifiers.
            jobs_data = []
            for job in jobs:
                if job.is_private:
                    jobs_data.append({
                        'job_id': None,
                        'job_name': 'Private job',
                        'description': None,
                        'user_email': None,
                        'is_private': True,
                        'status': job.status,
                        'created_at': job.created_at.isoformat() if job.created_at else None,
                        'started_at': None,
                        'completed_at': None,
                        'progress_percentage': job.progress_percentage,
                        'current_step': job.current_step,
                        'error_message': None,
                        'parameters': None,
                        'input_files': None,
                        'results_path': None,
                        'results_gcs_path': None,
                        'worker_id': None,
                        'worker_host': None,
                        'processing_time_seconds': None,
                        'memory_usage_mb': None,
                        'cpu_usage_percent': None,
                    })
                else:
                    jobs_data.append(job.to_dict())
        
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

@app.route('/api/create-job', methods=['POST'])
def create_job():
    """
    Create a new job and prepare for file uploads.
    Returns job_id for use with /api/jobs/<job_id>/upload endpoint.
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
        
        input_mode = data.get('input_mode', 'trajectory')
        parameters = data.get('parameters', {})
        is_private = data.get('is_private', False)
        job_name = data.get('job_name')
        
        # Create job in database with status 'pending_upload'
        mode_desc = 'Ensemble' if input_mode == 'ensemble' else 'Trajectory'
        with database_manager.get_session() as session:
            job_model = JobModel(
                job_name=job_name,
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
        
        logger.info(f"Created job {job_id} for local file upload")
        
        # Create job directories in local storage
        storage_manager.create_job_directories(job_id)
        
        # Update status to pending upload
        database_manager.update_job_status(
            job_id,
            DBJobStatus.PENDING,
            current_step="Waiting for file uploads",
            progress_percentage=0
        )
        
        # Return job info with upload endpoint
        return jsonify({
            'success': True,
            'job_id': job_id,
            'upload_endpoint': f'/api/jobs/{job_id}/upload',
            'expected_files': [f['filename'] for f in files_info],
            'message': 'Job created. Upload files using the upload endpoint.'
        })
        
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        return jsonify({'error': f'Failed to create job: {str(e)}'}), 500


@app.route('/api/jobs/<job_id>/upload', methods=['POST'])
def upload_job_file(job_id: str):
    """
    Upload a file for a job to local storage.
    Files are uploaded via multipart/form-data.
    """
    try:
        ensure_managers_initialized()
        
        # Check job exists and is in right state
        with database_manager.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return jsonify({'error': 'Job not found'}), 404
            
            if job.status not in [DBJobStatus.PENDING, DBJobStatus.UPLOADING]:
                return jsonify({
                    'error': f'Job is in {job.status.value} state, cannot upload files'
                }), 400
        
        # Update status to uploading
        database_manager.update_job_status(
            job_id,
            DBJobStatus.UPLOADING,
            current_step="Uploading files",
            progress_percentage=10
        )
        
        # Handle file upload
        if 'file' not in request.files:
            return jsonify({'error': 'No file in request'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No filename provided'}), 400
        
        filename = file.filename
        
        # Server-side file size validation (configurable per-file type)
        content_length = request.content_length

        lower_name = filename.lower()
        is_trajectory = lower_name.endswith('.xtc') or lower_name.endswith('.trr')
        max_file_size_mb = config.max_trajectory_file_size_mb if is_trajectory else config.max_other_file_size_mb
        max_file_size = max_file_size_mb * 1024 * 1024

        if content_length and content_length > max_file_size:
            logger.warning(
                f"Rejected file {filename}: Content-Length {content_length} exceeds {max_file_size_mb}MB limit"
            )
            return jsonify({
                'error': (
                    f"File too large. Maximum allowed size for {'trajectory' if is_trajectory else 'other'} files is "
                    f"{max_file_size_mb}MB. Your file: {content_length / 1024 / 1024:.1f}MB"
                )
            }), 413
        
        content = file.read()
        file_size = len(content)
        
        # Double-check actual content size
        if file_size > max_file_size:
            logger.warning(
                f"Rejected file {filename}: Actual size {file_size} exceeds {max_file_size_mb}MB limit"
            )
            return jsonify({
                'error': (
                    f"File too large. Maximum allowed size for {'trajectory' if is_trajectory else 'other'} files is "
                    f"{max_file_size_mb}MB. Your file: {file_size / 1024 / 1024:.1f}MB"
                )
            }), 413
        
        # Save to local storage
        file_path = storage_manager.upload_file_content(
            job_id=job_id,
            filename=filename,
            content=content,
            file_type="input"
        )
        
        logger.info(f"Uploaded file {filename} for job {job_id}: {len(content)} bytes")
        
        return jsonify({
            'success': True,
            'filename': filename,
            'size': len(content),
            'path': file_path
        })
        
    except Exception as e:
        logger.error(f"Error uploading file for job {job_id}: {e}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500


@app.route('/api/jobs/<job_id>/start', methods=['POST'])
def start_job_processing(job_id: str):
    """
    Start processing a job after all files have been uploaded.
    Verifies files exist in local storage and submits to Celery queue.
    """
    try:
        ensure_managers_initialized()
        
        # Get job from database and check status
        with database_manager.get_session() as session:
            job = session.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return jsonify({'error': 'Job not found'}), 404
            
            job_status = job.status
            expected_files = job.input_files or []
        
        # Check job is in the right state
        if job_status not in [DBJobStatus.PENDING, DBJobStatus.UPLOADING]:
            return jsonify({
                'error': f'Job is in {job_status.value} state, cannot start processing'
            }), 400
        
        # Verify files exist in local storage
        input_dir = storage_manager.get_input_directory(job_id)
        if not os.path.exists(input_dir):
            return jsonify({'error': 'No input files found'}), 400
        
        actual_files = os.listdir(input_dir)
        if not actual_files:
            return jsonify({'error': 'No input files found in storage'}), 400
        
        logger.info(f"Found {len(actual_files)} files in storage for job {job_id}")
        
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
            
            # Get parameters from job
            parameters = {}
            with database_manager.get_session() as session:
                job_model = session.query(JobModel).filter(JobModel.id == job_id).first()
                if job_model:
                    parameters = job_model.parameters or {}
            
            # Submit task to Celery
            task = process_grinn_job.delay(job_id, parameters)
            
            # Update job with Celery task ID
            database_manager.set_worker_info(job_id, task.id)
            
            logger.info(f"Submitted job {job_id} with Celery task ID {task.id}")
            
            return jsonify({
                'success': True,
                'job_id': job_id,
                'status': DBJobStatus.QUEUED.value,
                'message': 'Job queued for processing',
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
        logger.error(f"Error starting job {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


# ============================================================================
# Worker Management Endpoints
# ============================================================================

@app.route('/api/workers/register', methods=['POST'])
def register_worker():
    """
    Register a new worker with the system.
    Requires valid registration token for authentication.
    """
    try:
        ensure_managers_initialized()
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
        
        token = data.get('token')
        if not token:
            return jsonify({'error': 'Registration token is required'}), 401
        
        worker_id = data.get('worker_id')
        if not worker_id:
            return jsonify({'error': 'worker_id is required'}), 400
        
        facility = data.get('facility', 'default')
        capabilities = data.get('capabilities', {})
        metadata = data.get('metadata', {})
        
        try:
            result = worker_registry.register_worker(
                token=token,
                worker_id=worker_id,
                facility=facility,
                capabilities=capabilities,
                metadata=metadata
            )
            
            logger.info(f"Worker registered: {worker_id} at {facility}")
            return jsonify(result), 200
            
        except PermissionError as e:
            logger.warning(f"Invalid token for worker registration: {worker_id}")
            return jsonify({'error': 'Invalid registration token'}), 401
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
            
    except Exception as e:
        logger.error(f"Error registering worker: {e}")
        return jsonify({'error': f'Registration failed: {str(e)}'}), 500


@app.route('/api/workers/heartbeat', methods=['POST'])
def worker_heartbeat():
    """
    Update worker heartbeat to indicate it's still alive.
    """
    try:
        ensure_managers_initialized()
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
        
        worker_id = data.get('worker_id')
        if not worker_id:
            return jsonify({'error': 'worker_id is required'}), 400
        
        current_job = data.get('current_job')
        status = data.get('status', 'active')
        
        success = worker_registry.heartbeat(
            worker_id=worker_id,
            current_job=current_job,
            status=status
        )
        
        if success:
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Worker not found'}), 404
            
    except Exception as e:
        logger.error(f"Error processing heartbeat: {e}")
        return jsonify({'error': f'Heartbeat failed: {str(e)}'}), 500


@app.route('/api/workers', methods=['GET'])
def list_workers():
    """
    List all registered workers.
    Query params: active_only=true to show only active workers
    """
    try:
        ensure_managers_initialized()
        
        active_only = request.args.get('active_only', 'false').lower() == 'true'
        
        if active_only:
            workers = worker_registry.get_active_workers()
        else:
            workers = worker_registry.get_all_workers()
        
        stats = worker_registry.get_registry_stats()
        
        return jsonify({
            'success': True,
            'workers': workers,
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error listing workers: {e}")
        return jsonify({'error': f'Failed to list workers: {str(e)}'}), 500


@app.route('/api/workers/<worker_id>', methods=['GET'])
def get_worker(worker_id: str):
    """Get information about a specific worker."""
    try:
        ensure_managers_initialized()
        
        worker = worker_registry.get_worker(worker_id)
        if not worker:
            return jsonify({'error': 'Worker not found'}), 404
        
        return jsonify({
            'success': True,
            'worker': worker
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting worker {worker_id}: {e}")
        return jsonify({'error': f'Failed to get worker: {str(e)}'}), 500


@app.route('/api/workers/<worker_id>', methods=['DELETE'])
def deregister_worker(worker_id: str):
    """Remove a worker from the registry."""
    try:
        ensure_managers_initialized()
        
        # Optionally require admin token for deregistration
        # For now, allow any authenticated request
        
        success = worker_registry.deregister_worker(worker_id)
        
        if success:
            logger.info(f"Worker deregistered: {worker_id}")
            return jsonify({
                'success': True,
                'message': f'Worker {worker_id} deregistered'
            }), 200
        else:
            return jsonify({'error': 'Worker not found'}), 404
            
    except Exception as e:
        logger.error(f"Error deregistering worker {worker_id}: {e}")
        return jsonify({'error': f'Failed to deregister worker: {str(e)}'}), 500


@app.route('/api/workers/generate-token', methods=['POST'])
def generate_worker_token():
    """
    Generate a new worker registration token.
    This should be protected by admin authentication in production.
    """
    try:
        # In production, this should require admin authentication
        # For now, we just generate a new token
        token = generate_registration_token()
        
        logger.info("Generated new worker registration token")
        
        return jsonify({
            'success': True,
            'token': token,
            'message': 'Set this as WORKER_REGISTRATION_TOKEN environment variable'
        }), 200
        
    except Exception as e:
        logger.error(f"Error generating token: {e}")
        return jsonify({'error': f'Failed to generate token: {str(e)}'}), 500


@app.route('/api/storage/stats', methods=['GET'])
def get_storage_stats():
    """Get storage statistics."""
    try:
        ensure_managers_initialized()
        
        stats = storage_manager.get_storage_stats()
        
        return jsonify({
            'success': True,
            **stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting storage stats: {e}")
        return jsonify({'error': f'Failed to get storage stats: {str(e)}'}), 500


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
        from collections import deque
        
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
            # If preflight container was removed, attempt to return persisted preflight logs.
            try:
                output_dir = storage_manager.get_output_directory(job_id)
                preflight_log_path = os.path.join(output_dir, 'preflight.log')
                if os.path.exists(preflight_log_path) and os.path.getsize(preflight_log_path) > 0:
                    last_lines = deque(maxlen=tail)
                    with open(preflight_log_path, 'r', encoding='utf-8', errors='replace') as f:
                        for line in f:
                            last_lines.append(line)
                    logs_text = "".join(last_lines)
            except Exception as e:
                logger.warning(f"Could not read preflight.log for job {job_id}: {e}")

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


@app.route('/api/jobs/<job_id>/download', methods=['GET'])
def download_job_results(job_id):
    """
    Download complete job results as a compressed tar.gz archive.
    
    Returns:
        - tar.gz file containing all output files from the job
        - 404 if job not found or results not available
        - 500 on error
    """
    ensure_managers_initialized()
    
    try:
        from flask import send_file
        import tarfile
        import tempfile
        import shutil
        
        # Get job from database
        job = database_manager.get_job(job_id)
        if not job:
            return jsonify({
                'success': False,
                'error': f'Job {job_id} not found'
            }), 404
        
        # Check if job is completed
        if job.status != JobStatus.COMPLETED.value:
            return jsonify({
                'success': False,
                'error': f'Job {job_id} is not completed yet (status: {job.status})'
            }), 400
        
        # Get output directory from local storage
        output_dir = storage_manager.get_output_directory(job_id)
        
        # Check if output directory exists
        if not os.path.exists(output_dir):
            logger.error(f"Output directory not found for job {job_id}: {output_dir}")
            return jsonify({
                'success': False,
                'error': 'Results not found. Output directory may have been cleaned up.'
            }), 404
        
        # Create temporary tar.gz file
        temp_tar_path = tempfile.mktemp(suffix='.tar.gz')
        
        try:
            logger.info(f"Creating tar.gz archive for job {job_id} from {output_dir}")
            
            # Create tar.gz archive
            with tarfile.open(temp_tar_path, 'w:gz') as tar:
                # Add all files from output directory
                tar.add(output_dir, arcname=f'grinn-results-{job_id}')
            
            # Get file size for logging
            file_size_mb = os.path.getsize(temp_tar_path) / (1024 * 1024)
            logger.info(f"Created tar.gz archive for job {job_id}: {file_size_mb:.2f} MB")
            
            # Send file to user
            return send_file(
                temp_tar_path,
                mimetype='application/gzip',
                as_attachment=True,
                download_name=f'grinn-results-{job_id}.tar.gz'
            )
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_tar_path):
                try:
                    os.remove(temp_tar_path)
                except:
                    pass
            raise e
        
    except Exception as e:
        logger.error(f"Error downloading results for job {job_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    # Initialize managers
    if not initialize_managers():
        logger.error("Failed to initialize managers, exiting")
        exit(1)
    
    # Validate configuration
    config.validate()
    
    logger.info(f"Starting Backend API server on {config.backend_host}:{config.backend_port}")
    logger.info(f"Storage path: {config.storage_path}")
    logger.info(f"Job file retention: {config.job_file_retention_hours} hours")
    
    app.run(
        host=config.backend_host,
        port=config.backend_port,
        debug=config.frontend_debug
    )