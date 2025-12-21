"""
Shared configuration management for gRINN Web Service.
Handles environment variables, secrets, and service configuration.
"""

import os
import stat
import socket
from dataclasses import dataclass
from typing import Optional
import logging

# World-writable permissions for directories (rwxrwxrwx)
DIR_PERMISSIONS = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO  # 0o777


def makedirs_with_permissions(path: str, exist_ok: bool = True) -> None:
    """
    Create directories with world-writable permissions.
    This is needed when running as root in containers to allow
    other containers/users to write to the directories.
    """
    os.makedirs(path, mode=DIR_PERMISSIONS, exist_ok=exist_ok)
    # Ensure permissions are set (mkdir mode may be affected by umask)
    try:
        os.chmod(path, DIR_PERMISSIONS)
    except OSError:
        pass  # Best effort


# Load environment variables from a deterministic .env location.
# Rationale: Celery/other processes may be started with an arbitrary CWD, so
# relying on python-dotenv's default search can miss grinn-web/.env.
try:
    from dotenv import load_dotenv

    _here = os.path.dirname(os.path.abspath(__file__))
    _default_dotenv = os.path.normpath(os.path.join(_here, '..', '.env'))
    _dotenv_path = os.getenv('GRINN_WEB_DOTENV_PATH', _default_dotenv)

    if os.path.exists(_dotenv_path):
        load_dotenv(dotenv_path=_dotenv_path, override=False)
    else:
        # Fall back to default behavior (CWD-based) if file isn't present.
        load_dotenv(override=False)
except ImportError:
    # dotenv not available, use environment variables as-is
    pass

@dataclass
class Config:
    """Main configuration class for gRINN Web Service."""
    
    # Frontend settings
    frontend_host: str = "0.0.0.0"
    frontend_port: int = 8051
    frontend_debug: bool = False
    
    # Backend settings
    backend_host: str = "0.0.0.0"
    backend_port: int = 8050
    
    # Redis/Celery settings
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    celery_broker_url: str = None
    celery_result_backend: str = None
    
    # Local storage settings (use NFS mount for multi-worker setups)
    storage_path: str = None  # Will default to ~/.grinn-jobs or /data/grinn-jobs
    # Host storage path for Docker-in-Docker: when worker runs inside a container,
    # this is the HOST path that child containers (gRINN) need to mount
    host_storage_path: str = None
    
    # Worker registration settings
    worker_registration_token: str = None
    worker_max_concurrent_jobs: int = 2
    worker_heartbeat_interval_seconds: int = 30
    worker_heartbeat_timeout_seconds: int = 90
    
    # Job file cleanup settings
    job_file_retention_hours: float = 72  # 3 days default (supports fractional hours for testing)
    expired_job_retention_days: int = 30  # How long to keep expired job records in database
    cleanup_interval_seconds: float = 21600  # How often cleanup runs (6 hours default, supports fractional for testing)
    
    # gRINN Docker settings
    grinn_docker_image: str = "grinn:gromacs-2024.1"
    docker_timeout: int = 3600  # 1 hour default timeout
    default_gromacs_version: str = "2024.1"  # Default GROMACS version for dropdown
    
    # Dashboard settings
    dashboard_public_host: str = None  # Public hostname/IP for dashboard URLs (defaults to public_host)
    dashboard_max_instances: int = 10
    dashboard_idle_timeout_minutes: int = 30
    dashboard_cleanup_interval_seconds: int = 60
    dashboard_heartbeat_interval_seconds: int = 60
    
    # Public host settings (for client-facing URLs like downloads and dashboards)
    # Reads from PUBLIC_HOST env var, falls back to socket.gethostname()
    _public_host: str = None
    
    # Optional full URL overrides for reverse proxy setups
    # BACKEND_PUBLIC_URL: Full URL for API (e.g., https://example.com/api or https://example.com:5000)
    # DASHBOARD_PUBLIC_URL_TEMPLATE: URL template with {port} placeholder (e.g., https://example.com/dashboard/{port})
    _backend_public_url: str = None
    _dashboard_public_url_template: str = None
    
    # Job settings
    # max_trajectory_file_size_mb: Hard limit for trajectory-class files
    # (XTC/TRR in trajectory mode, PDB in ensemble mode)
    # Can also be set via LARGE_FILE_THRESHOLD_MB env var (takes precedence)
    max_trajectory_file_size_mb: int = 100
    max_other_file_size_mb: int = 10  # Limit for structure/topology files (PDB in trajectory mode, GRO, TOP, etc.)
    max_frames: Optional[int] = None  # Optional global cap for trajectory frames / ensemble models
    job_retention_days: int = 3  # Results kept for 3 days only
    max_concurrent_jobs: int = 10
    max_queued_jobs: int = 50  # Maximum number of jobs that can be queued at once
    
    # Security settings
    secret_key: str = None
    upload_folder: str = "/tmp/grinn-uploads"
    admin_api_key: str = None  # Admin API key for privileged operations
    
    # Example data settings (optional - for demo/testing)
    # Mode-specific paths for example data
    example_data_path_trajectory: Optional[str] = None  # Path to folder with trajectory mode example files
    example_data_path_ensemble: Optional[str] = None    # Path to folder with ensemble mode example files
    
    # Frontend base URL for constructing full URLs (e.g., for bookmark links)
    frontend_base_url: Optional[str] = None  # e.g., "https://grinn.example.com"
    
    def _get_default_storage_path(self) -> str:
        """Get default storage path based on environment."""
        # Check if /data/grinn-jobs exists and is writable (production Docker)
        if os.path.exists("/data") and os.access("/data", os.W_OK):
            return "/data/grinn-jobs"
        # Otherwise use user home directory (development)
        home = os.path.expanduser("~")
        return os.path.join(home, ".grinn-jobs")
    
    def __post_init__(self):
        """Load configuration from environment variables."""
        # Frontend
        self.frontend_host = os.getenv("FRONTEND_HOST", self.frontend_host)
        try:
            frontend_port_str = os.getenv("FRONTEND_PORT", str(self.frontend_port))
            self.frontend_port = int(frontend_port_str)
        except ValueError as e:
            logging.warning(f"Invalid FRONTEND_PORT value: {os.getenv('FRONTEND_PORT')}. Using default: {self.frontend_port}")
        
        self.frontend_debug = os.getenv("FRONTEND_DEBUG", "false").lower() == "true"
        
        # Backend
        self.backend_host = os.getenv("BACKEND_HOST", self.backend_host)
        try:
            backend_port_str = os.getenv("BACKEND_PORT", str(self.backend_port))
            self.backend_port = int(backend_port_str)
        except ValueError as e:
            logging.warning(f"Invalid BACKEND_PORT value: {os.getenv('BACKEND_PORT')}. Using default: {self.backend_port}")
        
        # Redis/Celery
        self.redis_host = os.getenv("REDIS_HOST", self.redis_host)
        try:
            redis_port_str = os.getenv("REDIS_PORT", str(self.redis_port))
            self.redis_port = int(redis_port_str)
        except ValueError as e:
            logging.warning(f"Invalid REDIS_PORT value: {os.getenv('REDIS_PORT')}. Using default: {self.redis_port}")
        
        try:
            redis_db_str = os.getenv("REDIS_DB", str(self.redis_db))
            self.redis_db = int(redis_db_str)
        except ValueError as e:
            logging.warning(f"Invalid REDIS_DB value: {os.getenv('REDIS_DB')}. Using default: {self.redis_db}")
        
        if not self.celery_broker_url:
            self.celery_broker_url = f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
        else:
            self.celery_broker_url = os.getenv("CELERY_BROKER_URL", self.celery_broker_url)
            
        if not self.celery_result_backend:
            self.celery_result_backend = f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
        else:
            self.celery_result_backend = os.getenv("CELERY_RESULT_BACKEND", self.celery_result_backend)
        
        # Local storage - use environment variable or smart default
        env_storage_path = os.getenv("STORAGE_PATH")
        if env_storage_path:
            self.storage_path = env_storage_path
        elif self.storage_path is None:
            self.storage_path = self._get_default_storage_path()
        
        # Host storage path for Docker-in-Docker scenarios:
        # When worker runs in a container, this is the HOST path for child container mounts
        # Defaults to storage_path if not set (standalone/non-Docker setups)
        self.host_storage_path = os.getenv("HOST_STORAGE_PATH", self.storage_path)
        
        # Worker registration
        self.worker_registration_token = os.getenv("WORKER_REGISTRATION_TOKEN", self.worker_registration_token)
        
        # Job file cleanup
        self.job_file_retention_hours = float(os.getenv("JOB_FILE_RETENTION_HOURS", self.job_file_retention_hours))
        self.expired_job_retention_days = int(os.getenv("EXPIRED_JOB_RETENTION_DAYS", self.expired_job_retention_days))
        self.cleanup_interval_seconds = float(os.getenv("CLEANUP_INTERVAL_SECONDS", self.cleanup_interval_seconds))
        
        # Log warning if cleanup interval is very low (could cause performance issues)
        if self.cleanup_interval_seconds < 60:
            logging.warning(f"CLEANUP_INTERVAL_SECONDS is set to {self.cleanup_interval_seconds}s - this is very frequent and intended for testing only")
        
        # gRINN Docker
        self.grinn_docker_image = os.getenv("GRINN_DOCKER_IMAGE", self.grinn_docker_image)
        self.docker_timeout = int(os.getenv("DOCKER_TIMEOUT", self.docker_timeout))
        
        # Public host settings (for client-facing URLs)
        # Priority: PUBLIC_HOST env var > socket.gethostname()
        self._public_host = os.getenv("PUBLIC_HOST") or socket.gethostname()
        
        # Dashboard public host (defaults to public_host if not explicitly set)
        # Priority: DASHBOARD_PUBLIC_HOST env var > public_host
        dashboard_host_env = os.getenv("DASHBOARD_PUBLIC_HOST")
        if dashboard_host_env:
            self.dashboard_public_host = dashboard_host_env
        else:
            self.dashboard_public_host = self._public_host
        
        # Full URL overrides for reverse proxy setups (optional)
        # These allow proxying API and dashboards through a single public port (e.g., nginx)
        self._backend_public_url = os.getenv("BACKEND_PUBLIC_URL")  # e.g., https://example.com/api
        self._dashboard_public_url_template = os.getenv("DASHBOARD_PUBLIC_URL_TEMPLATE")  # e.g., https://example.com/dashboard/{port}
        
        # Job settings
        # LARGE_FILE_THRESHOLD_MB takes precedence over MAX_TRAJECTORY_FILE_SIZE_MB if both are set
        large_threshold_env = os.getenv("LARGE_FILE_THRESHOLD_MB")
        traj_size_env = os.getenv("MAX_TRAJECTORY_FILE_SIZE_MB")
        if large_threshold_env:
            self.max_trajectory_file_size_mb = int(large_threshold_env)
        elif traj_size_env:
            self.max_trajectory_file_size_mb = int(traj_size_env)
        # else keep default
        
        self.max_other_file_size_mb = int(os.getenv("MAX_OTHER_FILE_SIZE_MB", self.max_other_file_size_mb))

        # Global max frames limit (optional)
        max_frames_raw = os.getenv("MAX_FRAMES")
        if max_frames_raw is None or max_frames_raw == "":
            self.max_frames = None
        else:
            try:
                parsed = int(max_frames_raw)
                self.max_frames = parsed if parsed > 0 else None
            except ValueError:
                logging.warning(f"Invalid MAX_FRAMES value: {max_frames_raw}. Disabling max frames limit.")
                self.max_frames = None

        self.job_retention_days = int(os.getenv("JOB_RETENTION_DAYS", self.job_retention_days))
        self.max_concurrent_jobs = int(os.getenv("MAX_CONCURRENT_JOBS", self.max_concurrent_jobs))
        self.max_queued_jobs = int(os.getenv("MAX_QUEUED_JOBS", self.max_queued_jobs))
        
        # Worker capacity settings
        self.worker_max_concurrent_jobs = int(os.getenv("WORKER_MAX_CONCURRENT_JOBS", self.worker_max_concurrent_jobs))
        self.worker_heartbeat_interval_seconds = int(os.getenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", self.worker_heartbeat_interval_seconds))
        self.worker_heartbeat_timeout_seconds = int(os.getenv("WORKER_HEARTBEAT_TIMEOUT_SECONDS", self.worker_heartbeat_timeout_seconds))
        
        # Dashboard settings
        self.dashboard_max_instances = int(os.getenv("DASHBOARD_MAX_INSTANCES", self.dashboard_max_instances))
        self.dashboard_idle_timeout_minutes = int(os.getenv("DASHBOARD_IDLE_TIMEOUT_MINUTES", self.dashboard_idle_timeout_minutes))
        self.dashboard_cleanup_interval_seconds = int(os.getenv("DASHBOARD_CLEANUP_INTERVAL_SECONDS", self.dashboard_cleanup_interval_seconds))
        self.dashboard_heartbeat_interval_seconds = int(os.getenv("DASHBOARD_HEARTBEAT_INTERVAL_SECONDS", self.dashboard_heartbeat_interval_seconds))
        
        # Security
        self.secret_key = os.getenv("SECRET_KEY", self.secret_key)
        if not self.secret_key:
            self.secret_key = os.urandom(32).hex()
            logging.warning("No SECRET_KEY provided, using random key. This will reset on restart.")
        
        self.upload_folder = os.getenv("UPLOAD_FOLDER", self.upload_folder)
        self.admin_api_key = os.getenv("ADMIN_API_KEY", self.admin_api_key)
        
        # Example data paths (optional, mode-specific)
        trajectory_path = os.getenv("EXAMPLE_DATA_PATH_TRAJECTORY")
        if trajectory_path and os.path.isdir(trajectory_path):
            self.example_data_path_trajectory = trajectory_path
        else:
            self.example_data_path_trajectory = None
        
        ensemble_path = os.getenv("EXAMPLE_DATA_PATH_ENSEMBLE")
        if ensemble_path and os.path.isdir(ensemble_path):
            self.example_data_path_ensemble = ensemble_path
        else:
            self.example_data_path_ensemble = None
        
        # Frontend base URL for bookmark links
        self.frontend_base_url = os.getenv("FRONTEND_BASE_URL", self.frontend_base_url)
        
        # Default GROMACS version for dropdown selection
        self.default_gromacs_version = os.getenv("DEFAULT_GROMACS_VERSION", self.default_gromacs_version)
        
        # Create upload folder if it doesn't exist (with world-writable permissions)
        makedirs_with_permissions(self.upload_folder)
        
        # Create storage directory if it doesn't exist (with world-writable permissions)
        makedirs_with_permissions(self.storage_path)
    
    def validate(self):
        """Validate configuration and raise errors for missing required settings."""
        errors = []
        
        # Validate storage path exists and is writable
        if not os.path.exists(self.storage_path):
            try:
                makedirs_with_permissions(self.storage_path)
            except Exception as e:
                errors.append(f"STORAGE_PATH '{self.storage_path}' cannot be created: {e}")
        elif not os.access(self.storage_path, os.W_OK):
            errors.append(f"STORAGE_PATH '{self.storage_path}' is not writable")
        
        # Validate retention hours (must be positive)
        if self.job_file_retention_hours <= 0:
            errors.append("JOB_FILE_RETENTION_HOURS must be positive")
        
        # Validate capacity settings (must be positive integers)
        if self.max_concurrent_jobs <= 0:
            errors.append("MAX_CONCURRENT_JOBS must be a positive integer")
        if self.max_queued_jobs <= 0:
            errors.append("MAX_QUEUED_JOBS must be a positive integer")
        if self.worker_max_concurrent_jobs <= 0:
            errors.append("WORKER_MAX_CONCURRENT_JOBS must be a positive integer")
        if self.dashboard_max_instances <= 0:
            errors.append("DASHBOARD_MAX_INSTANCES must be a positive integer")
        if self.dashboard_idle_timeout_minutes < 0:
            errors.append("DASHBOARD_IDLE_TIMEOUT_MINUTES must be non-negative")
        
        # Log warnings for potentially problematic capacity configurations
        if self.max_queued_jobs < self.max_concurrent_jobs:
            logging.warning(f"MAX_QUEUED_JOBS ({self.max_queued_jobs}) is less than MAX_CONCURRENT_JOBS ({self.max_concurrent_jobs})")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    @property
    def redis_url(self) -> str:
        """Get Redis URL for connections."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
    
    @property
    def backend_url(self) -> str:
        """Get backend URL for internal/server-side connections (resolves 0.0.0.0 to localhost)."""
        host = self.backend_host
        # Replace 0.0.0.0 with localhost for server-side connections
        if host == "0.0.0.0":
            host = "localhost"
        return f"http://{host}:{self.backend_port}"
    
    @property
    def public_host(self) -> str:
        """Get public hostname for client-facing URLs."""
        return self._public_host
    
    @property
    def backend_public_url(self) -> str:
        """Get backend URL for client-facing connections (downloads, etc.).
        
        If BACKEND_PUBLIC_URL is set, uses that (for reverse proxy setups).
        Otherwise, constructs URL from public_host and backend_port.
        """
        if self._backend_public_url:
            return self._backend_public_url.rstrip('/')
        return f"http://{self._public_host}:{self.backend_port}"
    
    def get_dashboard_public_url(self, job_id: str, port: int = None) -> str:
        """Get public URL for a dashboard instance.
        
        If DASHBOARD_PUBLIC_URL_TEMPLATE is set, uses that with {job_id} substitution.
        Otherwise, constructs URL from dashboard_public_host and port with the
        expected path that matches the dashboard container's DASH_URL_BASE_PATHNAME.
        
        Args:
            job_id: The job ID for the dashboard
            port: The port number the dashboard is running on (used for fallback URL)
            
        Returns:
            Public URL for the dashboard (always with trailing slash for Dash compatibility)
        """
        if self._dashboard_public_url_template:
            url = self._dashboard_public_url_template.replace('{job_id}', str(job_id))
            # Ensure trailing slash - required by Dash url_base_pathname
            if not url.endswith('/'):
                url += '/'
            return url
        # Fallback to direct port access (for local development without proxy)
        # Must include the full path that matches DASH_URL_BASE_PATHNAME in the container
        if port:
            return f"http://{self.dashboard_public_host}:{port}/api/dashboard/{job_id}/"
        raise ValueError("Port required when DASHBOARD_PUBLIC_URL_TEMPLATE is not set")


# Global configuration instance
config = Config()

# Setup logging
def setup_logging(level=logging.INFO):
    """Setup logging configuration."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('grinn-web.log')
        ]
    )

def get_config() -> Config:
    """Get the global configuration instance."""
    return config