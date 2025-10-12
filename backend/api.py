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
_managers_initialized = False

def initialize_managers():
    """Initialize storage and database managers."""
    global storage_manager, database_manager, _managers_initialized
    
    if _managers_initialized:
        return True
        
    try:
        storage_manager = get_storage_manager()
        database_manager = DatabaseManager()
        
        # Initialize database if needed
        database_manager.init_db()
        
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

@app.route('/api/jobs', methods=['POST'])
def submit_job():
    """Submit a new job for processing."""
    try:
        ensure_managers_initialized()
        data = request.get_json()
        
        # Validate required fields
        if not data.get('job_name'):
            return jsonify({'error': 'job_name is required'}), 400
        
        if not data.get('uploaded_files'):
            return jsonify({'error': 'uploaded_files is required'}), 400
        
        uploaded_files = data['uploaded_files']
        
        # Create job in database
        with database_manager.get_session() as session:
            job_model = JobModel(
                job_name=data['job_name'],
                description=data.get('description', 'gRINN trajectory analysis'),
                user_email=data.get('user_email'),
                is_private=data.get('is_private', False),
                parameters=data.get('parameters', {}),
                input_files=[{
                    'filename': f['filename'],
                    'file_type': f['file_type'],
                    'size_bytes': f['size_bytes']
                } for f in uploaded_files]
            )
            session.add(job_model)
            session.commit()
            job_id = job_model.id
        
        logger.info(f"Created job {job_id} in database")
        
        # Update status to uploading
        database_manager.update_job_status(
            job_id, 
            DBJobStatus.UPLOADING, 
            current_step="Uploading files to cloud storage",
            progress_percentage=10
        )
        
        # Upload files to storage
        try:
            # Create Job object for storage manager
            job_files = []
            for file_data in uploaded_files:
                job_file = JobFile(
                    filename=file_data['filename'],
                    file_type=FileType(file_data['file_type']),
                    size_bytes=file_data['size_bytes']
                )
                job_files.append(job_file)
            
            job_obj = Job(
                job_id=job_id,
                job_name=data['job_name'],
                description=data.get('description', 'gRINN trajectory analysis'),
                user_email=data.get('user_email'),
                is_private=data.get('is_private', False),
                parameters=JobParameters.from_dict(data.get('parameters', {})),
                input_files=job_files
            )
            
            files_for_upload = []
            for file_data in uploaded_files:
                files_for_upload.append({
                    'filename': file_data['filename'],
                    'content': file_data['content'],  # base64 content
                    'file_type': file_data['file_type'],
                    'size_bytes': file_data['size_bytes']
                })
            
            success = storage_manager.upload_job_files(job_obj, files_for_upload)
            if not success:
                database_manager.update_job_status(
                    job_id,
                    DBJobStatus.FAILED,
                    current_step="Failed to upload files to cloud storage",
                    error_message="File upload to storage failed"
                )
                return jsonify({'error': 'Failed to upload files'}), 500
                
        except Exception as e:
            database_manager.update_job_status(
                job_id,
                DBJobStatus.FAILED,
                current_step="File upload error",
                error_message=f"File upload error: {str(e)}"
            )
            return jsonify({'error': f'File upload failed: {str(e)}'}), 500
        
        # Update status to queued
        database_manager.update_job_status(
            job_id,
            DBJobStatus.QUEUED,
            current_step="Job queued for processing",
            progress_percentage=20
        )
        
        # Submit job to Celery processing queue
        try:
            from tasks import process_grinn_job
            task = process_grinn_job.delay(job_id, data.get('parameters', {}))
            
            # Update job with Celery task ID
            with database_manager.get_session() as session:
                job = session.query(JobModel).filter(JobModel.id == job_id).first()
                if job:
                    job.worker_id = task.id
                    session.commit()
            
            logger.info(f"Submitted job {job_id} with Celery task ID {task.id}")
            
        except Exception as e:
            database_manager.update_job_status(
                job_id,
                DBJobStatus.FAILED,
                current_step="Failed to queue job",
                error_message=f"Queue submission error: {str(e)}"
            )
            return jsonify({'error': f'Failed to queue job: {str(e)}'}), 500
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Job submitted successfully',
            'status': DBJobStatus.QUEUED.value,
            'monitor_url': f'/monitor/{job_id}'
        }), 201
        
    except Exception as e:
        logger.error(f"Error submitting job: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

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
            'id': job.id,
            'name': job.name,
            'description': job.description,
            'status': job.status.value,
            'status_message': job.status_message,
            'progress_percentage': job.progress_percentage or 0,
            'created_at': job.created_at.isoformat(),
            'updated_at': job.updated_at.isoformat(),
            'user_email': job.user_email,
            'parameters': job.parameters,
            'input_files': job.input_files,
            'result_files': job.result_files,
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
            'status': job.status.value,
            'status_message': job.status_message,
            'progress_percentage': job.progress_percentage or 0,
            'error_message': job.error_message,
            'updated_at': job.updated_at.isoformat(),
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
    """Get all jobs with optional status filtering."""
    try:
        ensure_managers_initialized()
        status_filter = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        with database_manager.get_session() as session:
            query = session.query(JobModel)
            
            # Apply status filter if provided
            if status_filter and status_filter != 'all':
                query = query.filter(JobModel.status == status_filter)
            
            # Order by creation time (newest first)
            query = query.order_by(JobModel.created_at.desc())
            
            # Apply pagination
            query = query.offset(offset).limit(limit)
            
            jobs = query.all()
            
            # Convert to dict format
            jobs_data = []
            for job in jobs:
                job_dict = job.to_dict()
                
                # If job is private, mask sensitive information in public view
                if job.is_private:
                    job_dict['job_name'] = "Private Job"
                    job_dict['description'] = "Private job details are hidden"
                    job_dict['user_email'] = None
                    # Keep status, timestamps, and progress for monitoring
                
                jobs_data.append(job_dict)
        
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