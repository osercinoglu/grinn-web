"""
REST API backend for gRINN Web Service.
Provides endpoints for job management and status monitoring.
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid

# Add shared modules to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'shared'))

from models import Job, JobStatus, JobParameters, FileType, JobSubmissionRequest
from config import get_config, setup_logging
from storage import get_storage_manager
from queue import get_queue_manager
from api_client import JobResponse

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
queue_manager = None

def initialize_managers():
    """Initialize storage and queue managers."""
    global storage_manager, queue_manager
    try:
        storage_manager = get_storage_manager()
        queue_manager = get_queue_manager()
        logger.info("Successfully initialized storage and queue managers")
    except Exception as e:
        logger.error(f"Failed to initialize managers: {e}")
        raise

@app.before_first_request
def setup():
    """Setup managers before first request."""
    initialize_managers()

# API Routes

@app.route('/api/health', methods=['GET'])
def health_check():
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
        data = request.get_json()
        
        # Validate required fields
        if not data.get('job_name'):
            return jsonify({'error': 'job_name is required'}), 400
        
        if not data.get('uploaded_files'):
            return jsonify({'error': 'uploaded_files is required'}), 400
        
        # Create job request
        job_request = JobSubmissionRequest(
            job_name=data['job_name'],
            description=data.get('description'),
            user_email=data.get('user_email'),
            parameters=data.get('parameters', {})
        )
        
        # Convert to job
        job = job_request.to_job()
        
        # Add uploaded files to job
        uploaded_files = data['uploaded_files']
        for file_data in uploaded_files:
            try:
                file_type = FileType(file_data['file_type'])
                job.add_file(
                    filename=file_data['filename'],
                    file_type=file_type,
                    size_bytes=file_data['size_bytes']
                )
            except ValueError as e:
                return jsonify({'error': f'Invalid file type: {file_data["file_type"]}'}), 400
        
        # Store job in queue
        queue_manager.store_job(job)
        
        # Upload files to storage
        job.update_status(JobStatus.UPLOADING, "Uploading files to cloud storage")
        queue_manager.store_job(job)
        
        try:
            success = storage_manager.upload_job_files(job, uploaded_files)
            if not success:
                job.update_status(JobStatus.FAILED, "Failed to upload files to cloud storage")
                queue_manager.store_job(job)
                return jsonify({'error': 'Failed to upload files'}), 500
        except Exception as e:
            job.update_status(JobStatus.FAILED, f"File upload error: {str(e)}")
            queue_manager.store_job(job)
            return jsonify({'error': f'File upload failed: {str(e)}'}), 500
        
        # Submit job to processing queue
        try:
            task_id = queue_manager.submit_job(job)
            logger.info(f"Submitted job {job.job_id} with task ID {task_id}")
        except Exception as e:
            job.update_status(JobStatus.FAILED, f"Failed to queue job: {str(e)}")
            queue_manager.store_job(job)
            return jsonify({'error': f'Failed to queue job: {str(e)}'}), 500
        
        return jsonify({
            'success': True,
            'job_id': job.job_id,
            'message': 'Job submitted successfully',
            'status': job.status.value
        }), 201
        
    except Exception as e:
        logger.error(f"Error submitting job: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/jobs', methods=['GET'])
def get_all_jobs():
    """Get list of all jobs with pagination."""
    try:
        limit = min(int(request.args.get('limit', 50)), 100)  # Max 100 items
        offset = int(request.args.get('offset', 0))
        
        all_jobs = queue_manager.get_all_jobs()
        
        # Apply pagination
        paginated_jobs = all_jobs[offset:offset+limit]
        
        # Convert to response format
        jobs_data = []
        for job in paginated_jobs:
            job_data = job.to_dict()
            # Remove sensitive/large data
            if 'uploaded_files' in job_data:
                # Keep metadata but remove file content
                job_data['uploaded_files'] = [
                    {k: v for k, v in f.items() if k != 'content'} 
                    for f in job_data['uploaded_files']
                ]
            jobs_data.append(job_data)
        
        return jsonify({
            'jobs': jobs_data,
            'total': len(all_jobs),
            'limit': limit,
            'offset': offset,
            'has_more': offset + limit < len(all_jobs)
        })
        
    except Exception as e:
        logger.error(f"Error getting all jobs: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id: str):
    """Get specific job information."""
    try:
        job = queue_manager.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        job_data = job.to_dict()
        # Remove file content for response
        if 'uploaded_files' in job_data:
            job_data['uploaded_files'] = [
                {k: v for k, v in f.items() if k != 'content'} 
                for f in job_data['uploaded_files']
            ]
        
        return jsonify(job_data)
        
    except Exception as e:
        logger.error(f"Error getting job {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/status', methods=['GET'])
def get_job_status(job_id: str):
    """Get job status and progress."""
    try:
        status_info = queue_manager.get_job_status(job_id)
        if not status_info:
            return jsonify({'error': 'Job not found'}), 404
        
        return jsonify(status_info)
        
    except Exception as e:
        logger.error(f"Error getting job status for {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id: str):
    """Cancel a job."""
    try:
        success = queue_manager.cancel_job(job_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Job cancelled successfully'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Job could not be cancelled'
            }), 400
        
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/results', methods=['GET'])
def get_job_results(job_id: str):
    """Get job results information."""
    try:
        job = queue_manager.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        if job.status != JobStatus.COMPLETED:
            return jsonify({'error': 'Job not completed yet'}), 400
        
        if not job.results_gcs_path:
            return jsonify({'error': 'No results available'}), 404
        
        # List available result files
        try:
            result_files = storage_manager.list_job_files(job_id, "output")
            
            # Generate signed URLs for result files
            file_urls = {}
            for file_info in result_files:
                try:
                    signed_url = storage_manager.generate_signed_url(
                        file_info['gcs_path'], 
                        expiration_hours=24
                    )
                    file_urls[file_info['filename']] = signed_url
                except Exception as e:
                    logger.warning(f"Failed to generate signed URL for {file_info['filename']}: {e}")
            
            return jsonify({
                'job_id': job_id,
                'results_available': True,
                'results_gcs_path': job.results_gcs_path,
                'files': result_files,
                'download_urls': file_urls
            })
            
        except Exception as e:
            logger.error(f"Error listing result files for job {job_id}: {e}")
            return jsonify({'error': f'Failed to access results: {str(e)}'}), 500
        
    except Exception as e:
        logger.error(f"Error getting job results for {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/jobs/<job_id>/dashboard', methods=['GET'])
def get_dashboard_url(job_id: str):
    """Get gRINN dashboard URL for job results."""
    try:
        job = queue_manager.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        if job.status != JobStatus.COMPLETED:
            return jsonify({'error': 'Job not completed yet'}), 400
        
        if not job.results_gcs_path:
            return jsonify({'error': 'No results available'}), 404
        
        # Create dashboard URL
        # In a real implementation, this would start a dashboard instance
        # with the results from GCS
        dashboard_url = f"/dashboard?job_id={job_id}&results_path={job.results_gcs_path}"
        
        return jsonify({
            'dashboard_url': dashboard_url,
            'job_id': job_id
        })
        
    except Exception as e:
        logger.error(f"Error getting dashboard URL for {job_id}: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/queue/stats', methods=['GET'])
def get_queue_stats():
    """Get queue statistics."""
    try:
        stats = queue_manager.get_queue_stats()
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/storage/health', methods=['GET'])
def storage_health():
    """Check storage system health."""
    try:
        healthy = storage_manager.check_bucket_access()
        return jsonify({
            'storage_healthy': healthy,
            'bucket_name': config.gcs_bucket_name
        })
        
    except Exception as e:
        logger.error(f"Error checking storage health: {e}")
        return jsonify({
            'storage_healthy': False,
            'error': str(e)
        }), 500

# Error handlers

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'error': 'Method not allowed'}), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    try:
        config.validate()
        logger.info("Starting gRINN Web Service Backend API")
        
        # Initialize managers
        initialize_managers()
        
        app.run(
            host=config.backend_host,
            port=config.backend_port,
            debug=config.frontend_debug  # Use same debug setting
        )
        
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print(f"Configuration error: {e}")
        print("Please check your environment variables and try again.")
    except Exception as e:
        logger.error(f"Failed to start backend API: {e}")
        print(f"Failed to start backend API: {e}")