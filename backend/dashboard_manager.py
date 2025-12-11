"""
Dashboard container management for gRINN Web Service.
Handles launching and managing gRINN dashboard Docker containers for job results viewing.
"""

import logging
import os
import subprocess
import json
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

class DashboardManager:
    """Manages gRINN dashboard Docker containers."""
    
    def __init__(self, storage_manager, start_port=None, end_port=None, docker_image=None, max_instances=None, public_host=None):
        """
        Initialize dashboard manager.
        
        Args:
            storage_manager: Storage manager instance for accessing job results
            start_port: Starting port for dashboard instances (default: from env or 8100)
            end_port: Ending port for dashboard instances (default: from env or 8200)
            docker_image: Docker image name (default: from env or 'grinn-dashboard:latest')
            max_instances: Maximum concurrent dashboard instances (default: from env or 10)
            public_host: Public hostname/IP for dashboard URLs (default: from env or 'localhost')
        """
        self.storage = storage_manager
        
        # Load configuration from environment or use defaults
        self.start_port = start_port or int(os.getenv('DASHBOARD_PORT_START', '8100'))
        self.end_port = end_port or int(os.getenv('DASHBOARD_PORT_END', '8200'))
        self.docker_image = docker_image or os.getenv('DASHBOARD_DOCKER_IMAGE', 'grinn-dashboard:latest')
        self.max_instances = max_instances or int(os.getenv('DASHBOARD_MAX_INSTANCES', '10'))
        self.timeout = int(os.getenv('DASHBOARD_TIMEOUT', '3600'))  # seconds, 0 to disable
        self.public_host = public_host or os.getenv('DASHBOARD_PUBLIC_HOST', 'localhost')
        
        self.active_dashboards = {}  # job_id -> {container_id, port, started_at}
        
        logger.info(f"DashboardManager initialized: ports {self.start_port}-{self.end_port}, "
                   f"image={self.docker_image}, max_instances={self.max_instances}, "
                   f"public_host={self.public_host}")
        
    def get_next_available_port(self) -> Optional[int]:
        """Find next available port for dashboard instance."""
        used_ports = {info['port'] for info in self.active_dashboards.values()}
        
        for port in range(self.start_port, self.end_port):
            if port not in used_ports:
                # Double-check port is actually available
                if self._is_port_available(port):
                    return port
        
        return None
    
    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available using socket binding."""
        import socket
        try:
            # Try to bind to the port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('', port))
                return True
        except OSError:
            # Port is in use or not available
            return False
        except Exception as e:
            logger.warning(f"Error checking port {port}: {e}")
            return False
    
    def start_dashboard(self, job_id: str) -> Dict[str, any]:
        """
        Start a dashboard container for a job.
        
        Args:
            job_id: The job ID to launch dashboard for
            
        Returns:
            Dictionary with dashboard info (port, container_id, url)
        """
        # Check if dashboard already running for this job
        if job_id in self.active_dashboards:
            info = self.active_dashboards[job_id]
            # Verify container is still running
            if self._is_container_running(info['container_id']):
                logger.info(f"Dashboard already running for job {job_id}")
                return {
                    'success': True,
                    'job_id': job_id,
                    'port': info['port'],
                    'url': f"http://{self.public_host}:{info['port']}",
                    'container_id': info['container_id'],
                    'already_running': True
                }
            else:
                # Container died, clean up
                del self.active_dashboards[job_id]
        
        # Check if max instances limit reached
        active_count = len([d for d in self.active_dashboards.values() 
                           if self._is_container_running(d['container_id'])])
        if active_count >= self.max_instances:
            logger.warning(f"Max dashboard instances reached ({self.max_instances})")
            return {
                'success': False,
                'error': f'Maximum number of dashboard instances ({self.max_instances}) already running. Please stop an unused dashboard first.'
            }
        
        # Get job output directory
        job_output_dir = self._get_job_output_dir(job_id)
        if not job_output_dir or not os.path.exists(job_output_dir):
            logger.error(f"Job output directory not found for {job_id}: {job_output_dir}")
            return {
                'success': False,
                'error': 'Job results not found or not yet available'
            }
        
        # Find available port
        port = self.get_next_available_port()
        if not port:
            logger.error(f"No available ports for dashboard (job {job_id})")
            return {
                'success': False,
                'error': 'No available ports for dashboard instances'
            }
        
        # Start Docker container
        try:
            container_name = f"grinn-dashboard-{job_id}"
            
            # Remove existing container if it exists (cleanup)
            subprocess.run(
                ['docker', 'rm', '-f', container_name],
                capture_output=True,
                timeout=10
            )
            
            # Start new container
            cmd = [
                'docker', 'run',
                '-d',  # Detached mode
                '--name', container_name,
                '-p', f"{port}:8050",  # Map to dashboard port (container listens on 8050)
                '-v', f"{job_output_dir}:/data:ro",  # Mount results as read-only
                '--rm',  # Auto-remove when stopped
                self.docker_image,
                'dashboard', '/data'
            ]
            
            logger.info(f"Starting dashboard for job {job_id}: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to start dashboard: {result.stderr}")
                return {
                    'success': False,
                    'error': f'Failed to start dashboard container: {result.stderr}'
                }
            
            container_id = result.stdout.strip()
            
            # Store dashboard info
            self.active_dashboards[job_id] = {
                'container_id': container_id,
                'container_name': container_name,
                'port': port,
                'started_at': datetime.utcnow().isoformat(),
                'job_output_dir': job_output_dir,
                'ready': False  # Will be set to True after health check passes
            }
            
            logger.info(f"Dashboard started for job {job_id}: container {container_id}, port {port}")
            logger.info(f"Dashboard is preparing data, this may take a moment...")
            
            # Wait for dashboard to be ready (in background, return immediately)
            # The frontend will poll the status endpoint to check readiness
            
            return {
                'success': True,
                'job_id': job_id,
                'port': port,
                'url': f"http://{self.public_host}:{port}",
                'container_id': container_id,
                'already_running': False
            }
            
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout starting dashboard for job {job_id}")
            return {
                'success': False,
                'error': 'Timeout starting dashboard container'
            }
        except Exception as e:
            logger.error(f"Error starting dashboard for job {job_id}: {e}")
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }
    
    def stop_dashboard(self, job_id: str) -> Dict[str, any]:
        """
        Stop a dashboard container.
        
        Args:
            job_id: The job ID whose dashboard to stop
            
        Returns:
            Dictionary with success status
        """
        if job_id not in self.active_dashboards:
            return {
                'success': False,
                'error': 'Dashboard not running for this job'
            }
        
        info = self.active_dashboards[job_id]
        container_id = info['container_id']
        
        try:
            subprocess.run(
                ['docker', 'stop', container_id],
                capture_output=True,
                timeout=30
            )
            
            del self.active_dashboards[job_id]
            logger.info(f"Dashboard stopped for job {job_id}")
            
            return {
                'success': True,
                'job_id': job_id
            }
            
        except Exception as e:
            logger.error(f"Error stopping dashboard for job {job_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_dashboard_status(self, job_id: str) -> Dict[str, any]:
        """Get status of dashboard for a job, including readiness."""
        if job_id not in self.active_dashboards:
            return {
                'running': False,
                'ready': False,
                'job_id': job_id
            }
        
        info = self.active_dashboards[job_id]
        
        # Verify container is actually running
        if not self._is_container_running(info['container_id']):
            del self.active_dashboards[job_id]
            return {
                'running': False,
                'ready': False,
                'job_id': job_id
            }
        
        # Check if dashboard is ready (if not already marked as ready)
        if not info.get('ready', False):
            # Add minimum delay before checking readiness
            # Dashboard containers need time to initialize Python, load libraries, process data
            started_at = datetime.fromisoformat(info['started_at'])
            elapsed = (datetime.utcnow() - started_at).total_seconds()
            
            # Only check readiness if at least 3 seconds have passed
            # This prevents false positives from port being open before app is ready
            if elapsed >= 3:
                if self._is_dashboard_ready(info['port']):
                    info['ready'] = True
                    logger.info(f"Dashboard for job {job_id} is now ready at port {info['port']} (after {elapsed:.1f}s)")
            else:
                logger.debug(f"Dashboard for job {job_id} still initializing ({elapsed:.1f}s elapsed, need 3s minimum)")
        
        return {
            'running': True,
            'ready': info.get('ready', False),
            'job_id': job_id,
            'port': info['port'],
            'url': f"http://{self.public_host}:{info['port']}",
            'started_at': info['started_at']
        }
    
    def list_active_dashboards(self) -> List[Dict[str, any]]:
        """List all active dashboard instances."""
        active = []
        
        for job_id, info in list(self.active_dashboards.items()):
            if self._is_container_running(info['container_id']):
                active.append({
                    'job_id': job_id,
                    'port': info['port'],
                    'url': f"http://{self.public_host}:{info['port']}",
                    'started_at': info['started_at']
                })
            else:
                # Clean up dead containers
                del self.active_dashboards[job_id]
        
        return active
    
    def cleanup_all(self):
        """Stop all dashboard containers."""
        for job_id in list(self.active_dashboards.keys()):
            try:
                self.stop_dashboard(job_id)
            except Exception as e:
                logger.error(f"Error cleaning up dashboard for {job_id}: {e}")
    
    def _is_container_running(self, container_id: str) -> bool:
        """Check if a container is running."""
        try:
            result = subprocess.run(
                ['docker', 'inspect', '-f', '{{.State.Running}}', container_id],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip() == 'true'
        except Exception:
            return False
    
    def _is_dashboard_ready(self, port: int) -> bool:
        """Check if dashboard is ready to serve requests with HTTP health check."""
        import requests
        try:
            # Make an HTTP request to the dashboard to verify it's actually serving content
            # Not just checking if port is open, but if Dash app is ready
            url = f"http://127.0.0.1:{port}/"
            response = requests.get(url, timeout=2)
            
            # Dashboard is ready if we get any successful response (200-299)
            # Even a 404 means the app is running, just need 200 for the main page
            if response.status_code == 200:
                logger.debug(f"Dashboard readiness check passed for port {port}")
                return True
            else:
                logger.debug(f"Dashboard at port {port} returned status {response.status_code}")
                return False
                
        except requests.exceptions.ConnectionError as e:
            # Connection refused or failed - port not ready yet
            logger.debug(f"Dashboard readiness check failed for port {port}: Connection failed")
            return False
        except requests.exceptions.Timeout as e:
            # Request timed out - dashboard not responding yet
            logger.debug(f"Dashboard readiness check failed for port {port}: Timeout")
            return False
        except Exception as e:
            logger.debug(f"Dashboard readiness check failed for port {port}: {e}")
            return False
    
    def _get_job_output_dir(self, job_id: str) -> Optional[str]:
        """Get the output directory for a job."""
        # This depends on the storage implementation
        if hasattr(self.storage, 'get_output_directory'):
            # LocalStorageManager
            return self.storage.get_output_directory(job_id)
        elif hasattr(self.storage, 'base_dir'):
            # Legacy fallback
            return os.path.join(self.storage.base_dir, job_id, 'output')
        else:
            logger.warning(f"Unknown storage type for job {job_id}")
            return None
    
    def get_dashboard_logs(self, job_id: str, since_timestamp: Optional[str] = None) -> Dict[str, any]:
        """
        Get container logs for a dashboard.
        
        Args:
            job_id: The job ID
            since_timestamp: Optional timestamp to get logs since (ISO format)
            
        Returns:
            Dictionary with logs and metadata
        """
        if job_id not in self.active_dashboards:
            return {
                'success': False,
                'error': 'Dashboard not found'
            }
        
        container_id = self.active_dashboards[job_id]['container_id']
        
        try:
            cmd = ['docker', 'logs', container_id]
            if since_timestamp:
                cmd.extend(['--since', since_timestamp])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Combine stdout and stderr
            logs = result.stdout + result.stderr
            
            return {
                'success': True,
                'logs': logs,
                'container_id': container_id,
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting logs for dashboard {job_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
