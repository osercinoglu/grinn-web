"""
Shared configuration management for gRINN Web Service.
Handles environment variables, secrets, and service configuration.
"""

import os
from dataclasses import dataclass
from typing import Optional
import logging

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
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
    
    # Worker registration settings
    worker_registration_token: str = None
    
    # Job file cleanup settings
    job_file_retention_hours: int = 72  # 3 days default
    
    # gRINN Docker settings
    grinn_docker_image: str = "grinn:latest"
    docker_timeout: int = 3600  # 1 hour default timeout
    
    # Dashboard settings
    dashboard_public_host: str = "localhost"  # Public hostname/IP for dashboard URLs
    
    # Job settings
    max_trajectory_file_size_mb: int = 100
    max_other_file_size_mb: int = 10
    job_retention_days: int = 3  # Results kept for 3 days only
    max_concurrent_jobs: int = 10
    
    # Security settings
    secret_key: str = None
    upload_folder: str = "/tmp/grinn-uploads"
    
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
        
        # Worker registration
        self.worker_registration_token = os.getenv("WORKER_REGISTRATION_TOKEN", self.worker_registration_token)
        
        # Job file cleanup
        self.job_file_retention_hours = int(os.getenv("JOB_FILE_RETENTION_HOURS", self.job_file_retention_hours))
        
        # gRINN Docker
        self.grinn_docker_image = os.getenv("GRINN_DOCKER_IMAGE", self.grinn_docker_image)
        self.docker_timeout = int(os.getenv("DOCKER_TIMEOUT", self.docker_timeout))
        
        # Dashboard settings
        self.dashboard_public_host = os.getenv("DASHBOARD_PUBLIC_HOST", self.dashboard_public_host)
        
        # Job settings
        self.max_trajectory_file_size_mb = int(os.getenv("MAX_TRAJECTORY_FILE_SIZE_MB", self.max_trajectory_file_size_mb))
        self.max_other_file_size_mb = int(os.getenv("MAX_OTHER_FILE_SIZE_MB", self.max_other_file_size_mb))
        self.job_retention_days = int(os.getenv("JOB_RETENTION_DAYS", self.job_retention_days))
        self.max_concurrent_jobs = int(os.getenv("MAX_CONCURRENT_JOBS", self.max_concurrent_jobs))
        
        # Security
        self.secret_key = os.getenv("SECRET_KEY", self.secret_key)
        if not self.secret_key:
            self.secret_key = os.urandom(32).hex()
            logging.warning("No SECRET_KEY provided, using random key. This will reset on restart.")
        
        self.upload_folder = os.getenv("UPLOAD_FOLDER", self.upload_folder)
        
        # Create upload folder if it doesn't exist
        os.makedirs(self.upload_folder, exist_ok=True)
        
        # Create storage directory if it doesn't exist
        os.makedirs(self.storage_path, exist_ok=True)
    
    def validate(self):
        """Validate configuration and raise errors for missing required settings."""
        errors = []
        
        # Validate storage path exists and is writable
        if not os.path.exists(self.storage_path):
            try:
                os.makedirs(self.storage_path, exist_ok=True)
            except Exception as e:
                errors.append(f"STORAGE_PATH '{self.storage_path}' cannot be created: {e}")
        elif not os.access(self.storage_path, os.W_OK):
            errors.append(f"STORAGE_PATH '{self.storage_path}' is not writable")
        
        # Validate retention hours
        if self.job_file_retention_hours < 1:
            errors.append("JOB_FILE_RETENTION_HOURS must be at least 1")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    @property
    def redis_url(self) -> str:
        """Get Redis URL for connections."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
    
    @property
    def backend_url(self) -> str:
        """Get backend URL for client connections (resolves 0.0.0.0 to localhost)."""
        host = self.backend_host
        # Replace 0.0.0.0 with localhost for client connections
        if host == "0.0.0.0":
            host = "localhost"
        return f"http://{host}:{self.backend_port}"


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