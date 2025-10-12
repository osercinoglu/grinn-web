#!/usr/bin/env python3
"""
Standalone gRINN Worker for Remote Deployment
===========================================

This script runs a Celery worker that connects to a remote gRINN frontend
and processes computational jobs using Docker containers.

Usage:
    python standalone-worker.py --frontend-host your.frontend.ip --facility facility-1

Requirements:
    - Docker installed and running
    - gRINN Docker image available
    - Network access to frontend Redis and database
    - GCS credentials (if using Google Cloud Storage)
"""

import os
import sys
import argparse
import logging
import signal
import time
from pathlib import Path

# Add shared modules to path
sys.path.insert(0, str(Path(__file__).parent / 'shared'))

def setup_logging(level=logging.INFO):
    """Setup logging configuration."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('grinn-worker.log')
        ]
    )

def validate_environment(args):
    """Validate that all required environment variables and dependencies are available."""
    logger = logging.getLogger(__name__)
    
    # Check Docker
    try:
        import docker
        client = docker.from_env()
        client.ping()
        logger.info("✅ Docker connection: OK")
    except Exception as e:
        logger.error(f"❌ Docker not available: {e}")
        return False
    
    # Check gRINN image
    grinn_image = args.grinn_image
    try:
        client.images.get(grinn_image)
        logger.info(f"✅ gRINN image found: {grinn_image}")
    except docker.errors.ImageNotFound:
        logger.warning(f"⚠️  gRINN image not found: {grinn_image}")
        logger.warning("You may need to build or pull the gRINN image")
    
    # Check network connectivity
    import socket
    
    # Test Redis connection
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((args.frontend_host, 6379))
        sock.close()
        if result == 0:
            logger.info("✅ Redis connectivity: OK")
        else:
            logger.error("❌ Cannot connect to Redis")
            return False
    except Exception as e:
        logger.error(f"❌ Redis connection test failed: {e}")
        return False
    
    # Test Database connection  
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((args.frontend_host, 5432))
        sock.close()
        if result == 0:
            logger.info("✅ Database connectivity: OK")
        else:
            logger.error("❌ Cannot connect to Database")
            return False
    except Exception as e:
        logger.error(f"❌ Database connection test failed: {e}")
        return False
    
    return True

def setup_environment(args):
    """Setup environment variables for the worker."""
    # Database connection
    db_password = args.db_password or os.getenv('POSTGRES_PASSWORD', 'grinn_password')
    os.environ['DATABASE_URL'] = f"postgresql://grinn_user:{db_password}@{args.frontend_host}:5432/grinn_web"
    
    # Redis connection
    redis_password = args.redis_password or os.getenv('REDIS_PASSWORD', '')
    os.environ['REDIS_HOST'] = args.frontend_host
    os.environ['REDIS_PORT'] = '6379'
    os.environ['REDIS_DB'] = '0'
    if redis_password:
        os.environ['REDIS_PASSWORD'] = redis_password
    
    # Worker identification
    os.environ['WORKER_FACILITY'] = args.facility
    os.environ['WORKER_ID'] = f"{args.facility}-{os.getpid()}"
    
    # gRINN configuration
    os.environ['GRINN_DOCKER_IMAGE'] = args.grinn_image
    os.environ['DOCKER_TIMEOUT'] = str(args.timeout)
    
    # Storage configuration
    if args.development:
        os.environ['DEVELOPMENT_MODE'] = 'true'
    else:
        os.environ['DEVELOPMENT_MODE'] = 'false'
        os.environ['GCS_BUCKET_NAME'] = args.gcs_bucket or os.getenv('GCS_BUCKET_NAME', '')
        os.environ['GCS_PROJECT_ID'] = args.gcs_project or os.getenv('GCS_PROJECT_ID', '')
        
        # GCS credentials
        gcs_creds = args.gcs_credentials or 'secrets/gcs-credentials.json'
        if os.path.exists(gcs_creds):
            os.environ['GCS_CREDENTIALS_PATH'] = os.path.abspath(gcs_creds)
        else:
            logging.warning(f"⚠️  GCS credentials not found at {gcs_creds}")

def run_worker(args):
    """Run the Celery worker."""
    logger = logging.getLogger(__name__)
    
    try:
        # Import Celery tasks
        sys.path.insert(0, str(Path(__file__).parent / 'backend'))
        from tasks import celery_app
        
        logger.info(f"🚀 Starting gRINN worker for facility: {args.facility}")
        logger.info(f"📡 Connected to frontend: {args.frontend_host}")
        
        # Run worker
        celery_app.worker_main([
            'worker',
            '--loglevel=info',
            '--concurrency=2',
            f'--hostname={args.facility}-worker@%h'
        ])
        
    except KeyboardInterrupt:
        logger.info("👋 Worker shutdown requested")
    except Exception as e:
        logger.error(f"❌ Worker error: {e}")
        return 1
    
    return 0

def main():
    parser = argparse.ArgumentParser(description='Standalone gRINN Worker')
    parser.add_argument('--frontend-host', required=True,
                       help='Frontend server hostname or IP')
    parser.add_argument('--facility', default='remote-facility',
                       help='Facility identifier for this worker')
    parser.add_argument('--db-password',
                       help='Database password (or set POSTGRES_PASSWORD env var)')
    parser.add_argument('--redis-password', 
                       help='Redis password (or set REDIS_PASSWORD env var)')
    parser.add_argument('--grinn-image', default='grinn:latest',
                       help='gRINN Docker image name')
    parser.add_argument('--timeout', type=int, default=7200,
                       help='Job timeout in seconds (default: 2 hours)')
    parser.add_argument('--development', action='store_true',
                       help='Run in development mode (mock storage)')
    parser.add_argument('--gcs-bucket',
                       help='Google Cloud Storage bucket name')
    parser.add_argument('--gcs-project',
                       help='Google Cloud Storage project ID')
    parser.add_argument('--gcs-credentials', default='secrets/gcs-credentials.json',
                       help='Path to GCS credentials JSON file')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(log_level)
    
    logger = logging.getLogger(__name__)
    logger.info("🔧 gRINN Standalone Worker Starting...")
    
    # Validate environment
    if not validate_environment(args):
        logger.error("❌ Environment validation failed")
        return 1
    
    # Setup environment
    setup_environment(args)
    
    # Run worker
    return run_worker(args)

if __name__ == '__main__':
    sys.exit(main())