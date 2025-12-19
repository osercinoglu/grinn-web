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

import redis

from shared.config import config as app_config

logger = logging.getLogger(__name__)

# Redis key prefix for dashboard state persistence
DASHBOARD_REDIS_KEY_PREFIX = "grinn:dashboard:"
DASHBOARD_REDIS_SET_KEY = "grinn:dashboards:active"


class DashboardManager:
    """Manages gRINN dashboard Docker containers with Redis persistence."""
    
    def __init__(self, storage_manager, start_port=None, end_port=None, docker_image=None, max_instances=None, public_host=None, redis_client=None):
        """
        Initialize dashboard manager.
        
        Args:
            storage_manager: Storage manager instance for accessing job results
            start_port: Starting port for dashboard instances (default: from env or 8100)
            end_port: Ending port for dashboard instances (default: from env or 8200)
            docker_image: Docker image name (default: from env or 'grinn-dashboard:latest')
            max_instances: Maximum concurrent dashboard instances (default: from env or 10)
            public_host: Public hostname/IP for dashboard URLs (default: from env or 'localhost')
            redis_client: Redis client instance for state persistence (optional, falls back to in-memory)
        """
        self.storage = storage_manager
        
        # Load configuration from environment or use defaults
        self.start_port = start_port or int(os.getenv('DASHBOARD_PORT_START', '8100'))
        self.end_port = end_port or int(os.getenv('DASHBOARD_PORT_END', '8200'))
        self.docker_image = docker_image or os.getenv('DASHBOARD_DOCKER_IMAGE', 'grinn-dashboard:latest')
        self.max_instances = max_instances or int(os.getenv('DASHBOARD_MAX_INSTANCES', '10'))
        self.timeout = int(os.getenv('DASHBOARD_TIMEOUT', '3600'))  # seconds, 0 to disable
        self.public_host = public_host or os.getenv('DASHBOARD_PUBLIC_HOST', app_config.public_host)
        self.idle_timeout_minutes = int(os.getenv('DASHBOARD_IDLE_TIMEOUT_MINUTES', '5'))  # Reduced from 30 to 5 for faster cleanup
        
        # Redis client for persistent state (optional)
        self.redis_client = redis_client
        
        # In-memory cache (synced with Redis if available)
        self._active_dashboards_cache = {}
        
        # Load existing dashboards from Redis on startup
        if self.redis_client:
            self._sync_from_redis()
        
        logger.info(f"DashboardManager initialized: ports {self.start_port}-{self.end_port}, "
                   f"image={self.docker_image}, max_instances={self.max_instances}, "
                   f"idle_timeout={self.idle_timeout_minutes}min, public_host={self.public_host}, "
                   f"redis_persistence={'enabled' if self.redis_client else 'disabled'}")
    
    @property
    def active_dashboards(self) -> Dict:
        """Get active dashboards dict (synced with Redis if available)."""
        return self._active_dashboards_cache
    
    @active_dashboards.setter
    def active_dashboards(self, value: Dict):
        """Set active dashboards dict (syncs to Redis if available)."""
        self._active_dashboards_cache = value
    
    def _sync_from_redis(self):
        """Sync in-memory cache from Redis."""
        if not self.redis_client:
            return
        try:
            job_ids = self.redis_client.smembers(DASHBOARD_REDIS_SET_KEY)
            self._active_dashboards_cache = {}
            for job_id_bytes in job_ids:
                job_id = job_id_bytes.decode('utf-8') if isinstance(job_id_bytes, bytes) else job_id_bytes
                dashboard_data = self.redis_client.get(f"{DASHBOARD_REDIS_KEY_PREFIX}{job_id}")
                if dashboard_data:
                    data = json.loads(dashboard_data.decode('utf-8') if isinstance(dashboard_data, bytes) else dashboard_data)
                    # Convert string timestamps back to datetime
                    if 'started_at' in data and isinstance(data['started_at'], str):
                        data['started_at'] = datetime.fromisoformat(data['started_at'])
                    if 'last_heartbeat' in data and isinstance(data['last_heartbeat'], str):
                        data['last_heartbeat'] = datetime.fromisoformat(data['last_heartbeat'])
                    self._active_dashboards_cache[job_id] = data
            logger.info(f"Synced {len(self._active_dashboards_cache)} dashboards from Redis")
        except Exception as e:
            logger.warning(f"Failed to sync dashboards from Redis: {e}")
    
    def _save_dashboard_to_redis(self, job_id: str, data: Dict):
        """Save dashboard data to Redis."""
        if not self.redis_client:
            return
        try:
            # Convert datetime objects to ISO strings for JSON serialization
            serializable_data = {}
            for key, value in data.items():
                if isinstance(value, datetime):
                    serializable_data[key] = value.isoformat()
                else:
                    serializable_data[key] = value
            
            self.redis_client.set(f"{DASHBOARD_REDIS_KEY_PREFIX}{job_id}", json.dumps(serializable_data))
            self.redis_client.sadd(DASHBOARD_REDIS_SET_KEY, job_id)
        except Exception as e:
            logger.warning(f"Failed to save dashboard {job_id} to Redis: {e}")
    
    def _remove_dashboard_from_redis(self, job_id: str):
        """Remove dashboard data from Redis."""
        if not self.redis_client:
            return
        try:
            self.redis_client.delete(f"{DASHBOARD_REDIS_KEY_PREFIX}{job_id}")
            self.redis_client.srem(DASHBOARD_REDIS_SET_KEY, job_id)
        except Exception as e:
            logger.warning(f"Failed to remove dashboard {job_id} from Redis: {e}")
        
    def get_next_available_port(self) -> Optional[int]:
        """Find next available port for dashboard instance."""
        used_ports = {info['port'] for info in self._active_dashboards_cache.values()}
        
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
        # Check capacity limit
        if len(self.active_dashboards) >= self.max_instances:
            # Calculate estimated wait time based on oldest dashboard
            oldest_start = min(info['started_at'] for info in self.active_dashboards.values())
            avg_session_duration = self.idle_timeout_minutes  # Assume average equals timeout
            elapsed = (datetime.utcnow() - oldest_start).total_seconds() / 60  # minutes
            estimated_wait = max(1, int(avg_session_duration - elapsed))
            
            logger.warning(f"Dashboard capacity reached ({self.max_instances} instances)")
            return {
                'success': False,
                'error': 'Dashboard capacity reached',
                'estimated_wait_minutes': estimated_wait,
                'message': f'Dashboard capacity reached. Estimated wait time: {estimated_wait} minutes. Please try again later.'
            }
        
        # Check if dashboard already running for this job
        if job_id in self.active_dashboards:
            info = self._active_dashboards_cache[job_id]
            # Verify container is still running
            if self._is_container_running(info['container_id']):
                logger.info(f"Dashboard already running for job {job_id}")
                # Update heartbeat
                info['last_heartbeat'] = datetime.utcnow()
                self._save_dashboard_to_redis(job_id, info)
                return {
                    'success': True,
                    'job_id': job_id,
                    'port': info['port'],
                    'url': app_config.get_dashboard_public_url(job_id, info['port']),
                    'container_id': info['container_id'],
                    'already_running': True
                }
            else:
                # Container died, clean up
                del self._active_dashboards_cache[job_id]
                self._remove_dashboard_from_redis(job_id)
        
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
                '-p', f"{port}:8060",  # Map to dashboard port (container listens on 8060)
                '-v', f"{job_output_dir}:/data:ro",  # Mount results as read-only
                '-v', '/var/run/docker.sock:/var/run/docker.sock',  # For chatbot DockerSandbox
                '--rm',  # Auto-remove when stopped
            ]

            # Forward LLM/chatbot environment variables if available.
            # Note: these must be present in the webapp process env (e.g., via compose env_file).
            # Disable Docker sandbox in containers (Docker-in-Docker not available)
            cmd.extend(['-e', 'PANDASAI_USE_DOCKER_SANDBOX=false'])
            
            for key in (
                'GEMINI_API_KEY',
                'GOOGLE_API_KEY',
                'ANTHROPIC_API_KEY',
                'PANDASAI_MODELS',
                'PANDASAI_DEFAULT_MODEL',
                'PANDASAI_MODEL',
                'PANDASAI_TOKEN_LIMIT',
            ):
                value = os.getenv(key)
                if value:
                    cmd.extend(['-e', f'{key}={value}'])
            
            # Pass backend URL for token usage API calls
            backend_host = os.getenv('BACKEND_HOST', 'localhost')
            backend_port = os.getenv('BACKEND_PORT', '5000')
            # Use host.docker.internal on Linux/Mac if running locally
            if backend_host in ('0.0.0.0', 'localhost', '127.0.0.1'):
                # Docker networking - use host gateway
                cmd.extend(['-e', f'GRINN_WEB_BACKEND_URL=http://host.docker.internal:{backend_port}'])
                cmd.extend(['--add-host', 'host.docker.internal:host-gateway'])
            else:
                cmd.extend(['-e', f'GRINN_WEB_BACKEND_URL=http://{backend_host}:{backend_port}'])
            
            # Pass job ID as environment variable for token tracking
            cmd.extend(['-e', f'GRINN_JOB_ID={job_id}'])
            
            # Set DASH_URL_BASE_PATHNAME for proper routing through the proxy
            # This tells the Dash app to expect requests at /api/dashboard/{job_id}/
            dash_base_pathname = f'/api/dashboard/{job_id}/'
            cmd.extend(['-e', f'DASH_URL_BASE_PATHNAME={dash_base_pathname}'])
            
            cmd.extend([
                self.docker_image,
                'dashboard', '/data', '--job-id', job_id
            ])
            
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
            
            # Store dashboard info with heartbeat tracking
            dashboard_info = {
                'container_id': container_id,
                'container_name': container_name,
                'port': port,
                'started_at': datetime.utcnow(),
                'last_heartbeat': datetime.utcnow(),
                'job_output_dir': job_output_dir,
                'ready': False  # Will be set to True after health check passes
            }
            self._active_dashboards_cache[job_id] = dashboard_info
            self._save_dashboard_to_redis(job_id, dashboard_info)
            
            logger.info(f"Dashboard started for job {job_id}: container {container_id}, port {port}")
            logger.info(f"Dashboard is preparing data, this may take a moment...")
            
            # Wait for dashboard to be ready (in background, return immediately)
            # The frontend will poll the status endpoint to check readiness
            
            return {
                'success': True,
                'job_id': job_id,
                'port': port,
                'url': app_config.get_dashboard_public_url(job_id, port),
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
        if job_id not in self._active_dashboards_cache:
            return {
                'success': False,
                'error': 'Dashboard not running for this job'
            }
        
        info = self._active_dashboards_cache[job_id]
        container_id = info['container_id']
        
        try:
            subprocess.run(
                ['docker', 'stop', container_id],
                capture_output=True,
                timeout=30
            )
            
            del self._active_dashboards_cache[job_id]
            self._remove_dashboard_from_redis(job_id)
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
        if job_id not in self._active_dashboards_cache:
            return {
                'running': False,
                'ready': False,
                'job_id': job_id
            }
        
        info = self._active_dashboards_cache[job_id]
        
        # Verify container is actually running
        if not self._is_container_running(info['container_id']):
            del self._active_dashboards_cache[job_id]
            self._remove_dashboard_from_redis(job_id)
            return {
                'running': False,
                'ready': False,
                'job_id': job_id
            }
        
        # Check if dashboard is ready (if not already marked as ready)
        if not info.get('ready', False):
            # Add minimum delay before checking readiness
            # Dashboard containers need time to initialize Python, load libraries, process data
            started_at = info['started_at'] if isinstance(info['started_at'], datetime) else datetime.fromisoformat(info['started_at'])
            elapsed = (datetime.utcnow() - started_at).total_seconds()
            
            # Only check readiness if at least 3 seconds have passed
            # This prevents false positives from port being open before app is ready
            if elapsed >= 3:
                if self._is_dashboard_ready(info['port'], job_id):
                    info['ready'] = True
                    self._save_dashboard_to_redis(job_id, info)
                    logger.info(f"Dashboard for job {job_id} is now ready at port {info['port']} (after {elapsed:.1f}s)")
            else:
                logger.debug(f"Dashboard for job {job_id} still initializing ({elapsed:.1f}s elapsed, need 3s minimum)")
        
        return {
            'running': True,
            'ready': info.get('ready', False),
            'job_id': job_id,
            'port': info['port'],
            'url': app_config.get_dashboard_public_url(job_id, info['port']),
            'started_at': info['started_at'].isoformat() if isinstance(info['started_at'], datetime) else info['started_at']
        }
    
    def list_active_dashboards(self) -> List[Dict[str, any]]:
        """List all active dashboard instances."""
        active = []
        
        for job_id, info in list(self._active_dashboards_cache.items()):
            if self._is_container_running(info['container_id']):
                active.append({
                    'job_id': job_id,
                    'port': info['port'],
                    'url': app_config.get_dashboard_public_url(job_id, info['port']),
                    'started_at': info['started_at'].isoformat() if isinstance(info['started_at'], datetime) else info['started_at']
                })
            else:
                # Clean up dead containers
                del self._active_dashboards_cache[job_id]
                self._remove_dashboard_from_redis(job_id)
        
        return active
    
    def get_dashboard_availability(self) -> Dict[str, any]:
        """Get dashboard availability status for capacity checking."""
        # First reconcile with actual running containers
        self.reconcile_containers()
        
        active_count = len(self._active_dashboards_cache)
        return {
            'available': active_count < self.max_instances,
            'active': active_count,
            'max': self.max_instances
        }
    
    def reconcile_containers(self):
        """Reconcile tracked dashboards with actual running containers."""
        for job_id in list(self._active_dashboards_cache.keys()):
            info = self._active_dashboards_cache[job_id]
            if not self._is_container_running(info['container_id']):
                logger.info(f"Removing stale dashboard entry for job {job_id} (container not running)")
                del self._active_dashboards_cache[job_id]
                self._remove_dashboard_from_redis(job_id)
    
    def cleanup_all(self):
        """Stop all dashboard containers."""
        for job_id in list(self._active_dashboards_cache.keys()):
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
    
    def _is_dashboard_ready(self, port: int, job_id: str) -> bool:
        """Check if dashboard is ready to serve requests with HTTP health check."""
        import requests
        try:
            # Make an HTTP request to the dashboard's actual path
            # Dashboard is configured with DASH_URL_BASE_PATHNAME=/api/dashboard/{job_id}/
            url = f"http://127.0.0.1:{port}/api/dashboard/{job_id}/"
            response = requests.get(url, timeout=2)
            
            # Dashboard is ready if we get any successful response (200-299)
            # Even a 404 means the app is running, just need 200 for the main page
            if response.status_code == 200:
                logger.debug(f"Dashboard readiness check passed for port {port} at path /api/dashboard/{job_id}/")
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
        if job_id not in self._active_dashboards_cache:
            return {
                'success': False,
                'error': 'Dashboard not found'
            }
        
        container_id = self._active_dashboards_cache[job_id]['container_id']
        
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
    
    def cleanup_idle_dashboards(self) -> int:
        """
        Stop dashboards that have been idle (no heartbeat) for too long.
        
        Returns:
            Number of dashboards cleaned up
        """
        if self.idle_timeout_minutes <= 0:
            return 0  # Idle cleanup disabled
        
        from datetime import timedelta
        timeout = timedelta(minutes=self.idle_timeout_minutes)
        now = datetime.utcnow()
        cleanup_count = 0
        
        # First reconcile with actual containers
        self.reconcile_containers()
        
        # Find idle dashboards
        idle_jobs = []
        for job_id, info in self._active_dashboards_cache.items():
            last_heartbeat = info.get('last_heartbeat', info.get('started_at'))
            if isinstance(last_heartbeat, str):
                last_heartbeat = datetime.fromisoformat(last_heartbeat)
            if last_heartbeat and (now - last_heartbeat) > timeout:
                idle_jobs.append(job_id)
        
        # Stop idle dashboards
        for job_id in idle_jobs:
            try:
                logger.info(f"Stopping idle dashboard for job {job_id} (no heartbeat for >{self.idle_timeout_minutes}min)")
                self.stop_dashboard(job_id)
                cleanup_count += 1
            except Exception as e:
                logger.error(f"Error stopping idle dashboard {job_id}: {e}")
        
        return cleanup_count
