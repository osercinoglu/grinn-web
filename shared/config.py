"""
Shared configuration management for gRINN Web Service.
Handles environment variables, secrets, and service configuration.
"""

import os
from dataclasses import dataclass
from typing import Optional
import logging

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
    
    # Google Cloud Storage settings
    gcs_bucket_name: str = None
    gcs_credentials_path: str = None
    gcs_project_id: str = None
    
    # gRINN Docker settings
    grinn_docker_image: str = "grinn:latest"
    docker_timeout: int = 3600  # 1 hour default timeout
    
    # Job settings
    max_trajectory_file_size_mb: int = 100
    max_other_file_size_mb: int = 10
    job_retention_days: int = 3  # Results kept for 3 days only
    max_concurrent_jobs: int = 10
    
    # Security settings
    secret_key: str = None
    upload_folder: str = "/tmp/grinn-uploads"
    
    def __post_init__(self):
        """Load configuration from environment variables."""
        # Frontend
        self.frontend_host = os.getenv("FRONTEND_HOST", self.frontend_host)
        self.frontend_port = int(os.getenv("FRONTEND_PORT", self.frontend_port))
        self.frontend_debug = os.getenv("FRONTEND_DEBUG", "false").lower() == "true"
        
        # Backend
        self.backend_host = os.getenv("BACKEND_HOST", self.backend_host)
        self.backend_port = int(os.getenv("BACKEND_PORT", self.backend_port))
        
        # Redis/Celery
        self.redis_host = os.getenv("REDIS_HOST", self.redis_host)
        self.redis_port = int(os.getenv("REDIS_PORT", self.redis_port))
        self.redis_db = int(os.getenv("REDIS_DB", self.redis_db))
        
        if not self.celery_broker_url:
            self.celery_broker_url = f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
        else:
            self.celery_broker_url = os.getenv("CELERY_BROKER_URL", self.celery_broker_url)
            
        if not self.celery_result_backend:
            self.celery_result_backend = f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
        else:
            self.celery_result_backend = os.getenv("CELERY_RESULT_BACKEND", self.celery_result_backend)
        
        # Google Cloud Storage
        self.gcs_bucket_name = os.getenv("GCS_BUCKET_NAME", self.gcs_bucket_name)
        self.gcs_credentials_path = os.getenv("GCS_CREDENTIALS_PATH", self.gcs_credentials_path)
        self.gcs_project_id = os.getenv("GCS_PROJECT_ID", self.gcs_project_id)
        
        # gRINN Docker
        self.grinn_docker_image = os.getenv("GRINN_DOCKER_IMAGE", self.grinn_docker_image)
        self.docker_timeout = int(os.getenv("DOCKER_TIMEOUT", self.docker_timeout))
        
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
    
    def validate(self, skip_gcs_validation=False):
        """Validate configuration and raise errors for missing required settings."""
        errors = []
        
        # Skip GCS validation in development mode
        if not skip_gcs_validation:
            if not self.gcs_bucket_name:
                errors.append("GCS_BUCKET_NAME is required")
            
            if not self.gcs_project_id:
                errors.append("GCS_PROJECT_ID is required")
            
            if not self.gcs_credentials_path or not os.path.exists(self.gcs_credentials_path):
                errors.append("GCS_CREDENTIALS_PATH must point to a valid credentials file")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    @property
    def redis_url(self) -> str:
        """Get Redis URL for connections."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


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