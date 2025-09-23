"""
API client for frontend to communicate with backend services.
Handles job submission, status checking, and result retrieval.
"""

import requests
import logging
from typing import Dict, Any, Optional, List
import json
from datetime import datetime

from .models import Job, JobStatus, JobSubmissionRequest, JobResponse

logger = logging.getLogger(__name__)

class GrinnWebAPIClient:
    """Client for interacting with gRINN Web Service backend API."""
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'gRINN-Web-Frontend/1.0'
        })
    
    def _make_request(self, method: str, endpoint: str, 
                     data: Optional[Dict] = None, 
                     params: Optional[Dict] = None,
                     timeout: int = 30) -> requests.Response:
        """Make HTTP request with error handling."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.request(
                method=method,
                url=url,
                json=data,
                params=params,
                timeout=timeout
            )
            response.raise_for_status()
            return response
            
        except requests.exceptions.ConnectionError:
            logger.error(f"Failed to connect to backend API at {url}")
            raise
        except requests.exceptions.Timeout:
            logger.error(f"Request to {url} timed out")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error making request to {url}: {e}")
            raise
    
    def submit_job(self, job_request: JobSubmissionRequest, 
                   uploaded_files: List[Dict[str, Any]]) -> JobResponse:
        """
        Submit a new job for processing.
        
        Args:
            job_request: Job submission request object
            uploaded_files: List of uploaded file data
            
        Returns:
            JobResponse with job ID or error information
        """
        try:
            payload = {
                'job_name': job_request.job_name,
                'description': job_request.description,
                'user_email': job_request.user_email,
                'parameters': job_request.parameters or {},
                'uploaded_files': uploaded_files
            }
            
            response = self._make_request('POST', '/api/jobs', data=payload)
            response_data = response.json()
            
            return JobResponse(
                success=True,
                job_id=response_data.get('job_id'),
                message=response_data.get('message'),
                data=response_data
            )
            
        except Exception as e:
            logger.error(f"Failed to submit job: {e}")
            return JobResponse(
                success=False,
                error=str(e)
            )
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current status of a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job status dictionary or None if not found
        """
        try:
            response = self._make_request('GET', f'/api/jobs/{job_id}/status')
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            logger.error(f"Failed to get job status for {job_id}: {e}")
            return None
    
    def get_all_jobs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get list of all jobs.
        
        Args:
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip
            
        Returns:
            List of job dictionaries
        """
        try:
            params = {'limit': limit, 'offset': offset}
            response = self._make_request('GET', '/api/jobs', params=params)
            return response.json().get('jobs', [])
            
        except Exception as e:
            logger.error(f"Failed to get all jobs: {e}")
            return []
    
    def cancel_job(self, job_id: str) -> JobResponse:
        """
        Cancel a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            JobResponse indicating success or failure
        """
        try:
            response = self._make_request('POST', f'/api/jobs/{job_id}/cancel')
            response_data = response.json()
            
            return JobResponse(
                success=response_data.get('success', False),
                message=response_data.get('message'),
                data=response_data
            )
            
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return JobResponse(
                success=False,
                error=str(e)
            )
    
    def get_job_results(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job results information including download URLs.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Results information or None if not available
        """
        try:
            response = self._make_request('GET', f'/api/jobs/{job_id}/results')
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            logger.error(f"Failed to get job results for {job_id}: {e}")
            return None
    
    def get_dashboard_url(self, job_id: str) -> Optional[str]:
        """
        Get URL for gRINN dashboard with job results.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Dashboard URL or None if not available
        """
        try:
            response = self._make_request('GET', f'/api/jobs/{job_id}/dashboard')
            return response.json().get('dashboard_url')
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception as e:
            logger.error(f"Failed to get dashboard URL for {job_id}: {e}")
            return None
    
    def health_check(self) -> bool:
        """
        Check if backend API is healthy.
        
        Returns:
            True if backend is healthy, False otherwise
        """
        try:
            response = self._make_request('GET', '/api/health')
            return response.json().get('status') == 'healthy'
            
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False
    
    def get_queue_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get queue statistics from backend.
        
        Returns:
            Queue statistics or None if not available
        """
        try:
            response = self._make_request('GET', '/api/queue/stats')
            return response.json()
            
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return None


# Mock implementation for development/testing when backend is not available
class MockAPIClient:
    """Mock API client for development and testing."""
    
    def __init__(self):
        self.jobs = {}
        self.job_counter = 0
    
    def submit_job(self, job_request: JobSubmissionRequest, 
                   uploaded_files: List[Dict[str, Any]]) -> JobResponse:
        """Mock job submission."""
        self.job_counter += 1
        job_id = f"mock_job_{self.job_counter:04d}"
        
        # Create mock job
        job = job_request.to_job()
        job.job_id = job_id
        job.update_status(JobStatus.UPLOADING, "Uploading files...")
        
        self.jobs[job_id] = job
        
        return JobResponse(
            success=True,
            job_id=job_id,
            message="Job submitted successfully (mock mode)"
        )
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Mock job status retrieval."""
        if job_id not in self.jobs:
            return None
        
        job = self.jobs[job_id]
        
        # Simulate job progression
        import time
        elapsed = (datetime.utcnow() - job.created_at).total_seconds()
        
        if elapsed < 5:
            job.update_status(JobStatus.UPLOADING, "Uploading files...")
            job.progress_percentage = 10
        elif elapsed < 10:
            job.update_status(JobStatus.QUEUED, "Waiting in queue...")
            job.progress_percentage = 20
        elif elapsed < 30:
            job.update_status(JobStatus.RUNNING, "Running analysis...")
            job.progress_percentage = min(90, 30 + (elapsed - 10) * 3)
        else:
            job.update_status(JobStatus.COMPLETED, "Analysis completed")
            job.progress_percentage = 100
            job.results_gcs_path = f"gs://mock-bucket/jobs/{job_id}/output/"
        
        return {
            'job_id': job.job_id,
            'status': job.status.value,
            'progress_percentage': job.progress_percentage,
            'current_step': job.current_step,
            'created_at': job.created_at.isoformat(),
            'updated_at': job.updated_at.isoformat(),
            'error_message': job.error_message
        }
    
    def get_all_jobs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Mock all jobs retrieval."""
        job_list = []
        for job in sorted(self.jobs.values(), key=lambda x: x.created_at, reverse=True):
            status = self.get_job_status(job.job_id)
            if status:
                job_list.append(status)
        
        return job_list[offset:offset+limit]
    
    def cancel_job(self, job_id: str) -> JobResponse:
        """Mock job cancellation."""
        if job_id not in self.jobs:
            return JobResponse(success=False, error="Job not found")
        
        job = self.jobs[job_id]
        job.update_status(JobStatus.CANCELLED, "Job cancelled by user")
        
        return JobResponse(
            success=True,
            message="Job cancelled successfully (mock mode)"
        )
    
    def get_job_results(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Mock job results retrieval."""
        if job_id not in self.jobs:
            return None
        
        job = self.jobs[job_id]
        if job.status != JobStatus.COMPLETED:
            return None
        
        return {
            'job_id': job_id,
            'results_available': True,
            'results_gcs_path': job.results_gcs_path,
            'files': [
                'energies_intEnTotal.csv',
                'energies_intEnVdW.csv',
                'energies_intEnElec.csv',
                'system_dry.pdb',
                'network_analysis.json'
            ]
        }
    
    def get_dashboard_url(self, job_id: str) -> Optional[str]:
        """Mock dashboard URL generation."""
        if job_id not in self.jobs:
            return None
        
        job = self.jobs[job_id]
        if job.status != JobStatus.COMPLETED:
            return None
        
        return f"/dashboard?job_id={job_id}&results_path={job.results_gcs_path}"
    
    def health_check(self) -> bool:
        """Mock health check."""
        return True
    
    def get_queue_stats(self) -> Optional[Dict[str, Any]]:
        """Mock queue statistics."""
        stats = {'total_jobs': len(self.jobs), 'by_status': {}}
        
        for status in JobStatus:
            count = sum(1 for job in self.jobs.values() if job.status == status)
            stats['by_status'][status.value] = count
        
        return stats


# Factory function to create appropriate client
def create_api_client(backend_url: Optional[str] = None, use_mock: bool = False) -> GrinnWebAPIClient:
    """
    Create API client instance.
    
    Args:
        backend_url: Backend API URL (default: http://localhost:5000)
        use_mock: Use mock client for development
        
    Returns:
        API client instance
    """
    if use_mock:
        logger.info("Using mock API client")
        return MockAPIClient()
    
    backend_url = backend_url or "http://localhost:5000"
    client = GrinnWebAPIClient(backend_url)
    
    # Test connection
    if client.health_check():
        logger.info(f"Connected to backend API at {backend_url}")
        return client
    else:
        logger.warning(f"Backend API at {backend_url} is not available, using mock client")
        return MockAPIClient()