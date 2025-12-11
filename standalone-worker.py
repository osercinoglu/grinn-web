#!/usr/bin/env python3
"""
Standalone gRINN Worker for Remote Deployment
===========================================

This script runs a Celery worker that connects to a remote gRINN frontend
and processes computational jobs using Docker containers.

Usage:
    python standalone-worker.py --frontend-host your.frontend.ip --facility facility-1 --registration-token YOUR_TOKEN

Requirements:
    - Docker installed and running
    - gRINN Docker image available
    - Network access to frontend Redis and database
    - NFS mount for shared storage (or local storage if single-node)
    - Valid registration token for worker authentication
"""

import os
import sys
import argparse
import logging
import signal
import time
import threading
import requests
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
    
    # Check storage path (NFS mount or local)
    storage_path = args.storage_path
    if os.path.exists(storage_path):
        if os.access(storage_path, os.W_OK):
            logger.info(f"✅ Storage path writable: {storage_path}")
        else:
            logger.error(f"❌ Storage path not writable: {storage_path}")
            return False
    else:
        try:
            os.makedirs(storage_path, exist_ok=True)
            logger.info(f"✅ Storage path created: {storage_path}")
        except Exception as e:
            logger.error(f"❌ Cannot create storage path: {e}")
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
    worker_id = f"{args.facility}-{os.getpid()}"
    os.environ['WORKER_ID'] = worker_id
    
    # gRINN configuration
    os.environ['GRINN_DOCKER_IMAGE'] = args.grinn_image
    os.environ['DOCKER_TIMEOUT'] = str(args.timeout)
    
    # Local storage configuration (NFS mount point)
    os.environ['STORAGE_PATH'] = args.storage_path
    
    # Worker registration token
    if args.registration_token:
        os.environ['WORKER_REGISTRATION_TOKEN'] = args.registration_token
    
    return worker_id


def register_worker(args, worker_id):
    """Register this worker with the frontend."""
    logger = logging.getLogger(__name__)
    
    if not args.registration_token:
        logger.warning("⚠️  No registration token provided, skipping worker registration")
        return True
    
    try:
        import platform
        import docker
        
        # Gather worker capabilities
        docker_client = docker.from_env()
        docker_info = docker_client.info()
        
        capabilities = {
            'cpu_cores': os.cpu_count(),
            'docker_cpus': docker_info.get('NCPU', 0),
            'docker_memory_gb': round(docker_info.get('MemTotal', 0) / (1024**3), 2),
        }
        
        metadata = {
            'hostname': platform.node(),
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'grinn_image': args.grinn_image,
        }
        
        # Register with frontend
        register_url = f"http://{args.frontend_host}:{args.backend_port}/api/workers/register"
        response = requests.post(
            register_url,
            json={
                'token': args.registration_token,
                'worker_id': worker_id,
                'facility': args.facility,
                'capabilities': capabilities,
                'metadata': metadata
            },
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Worker registered: {worker_id}")
            return True
        elif response.status_code == 401:
            logger.error("❌ Invalid registration token")
            return False
        else:
            error_msg = response.json().get('error', 'Unknown error')
            logger.error(f"❌ Registration failed: {error_msg}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Registration error: {e}")
        return False


def heartbeat_loop(args, worker_id, stop_event):
    """Background thread to send periodic heartbeats."""
    logger = logging.getLogger(__name__)
    
    heartbeat_url = f"http://{args.frontend_host}:{args.backend_port}/api/workers/heartbeat"
    
    while not stop_event.is_set():
        try:
            response = requests.post(
                heartbeat_url,
                json={
                    'worker_id': worker_id,
                    'status': 'active'
                },
                timeout=5
            )
            
            if response.status_code != 200:
                logger.warning(f"Heartbeat failed: {response.status_code}")
                
        except Exception as e:
            logger.debug(f"Heartbeat error: {e}")
        
        # Wait for next heartbeat (every 60 seconds)
        stop_event.wait(60)


def run_worker(args, worker_id):
    """Run the Celery worker with heartbeat."""
    logger = logging.getLogger(__name__)
    
    # Start heartbeat thread
    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(args, worker_id, stop_event),
        daemon=True
    )
    heartbeat_thread.start()
    
    try:
        # Import Celery tasks
        sys.path.insert(0, str(Path(__file__).parent / 'backend'))
        from tasks import celery_app
        
        logger.info(f"🚀 Starting gRINN worker for facility: {args.facility}")
        logger.info(f"📡 Connected to frontend: {args.frontend_host}")
        logger.info(f"📁 Storage path: {args.storage_path}")
        
        # Run worker
        celery_app.worker_main([
            'worker',
            '--loglevel=info',
            f'--concurrency={args.concurrency}',
            f'--hostname={args.facility}-worker@%h'
        ])
        
    except KeyboardInterrupt:
        logger.info("👋 Worker shutdown requested")
    except Exception as e:
        logger.error(f"❌ Worker error: {e}")
        return 1
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=5)
    
    return 0


def main():
    parser = argparse.ArgumentParser(description='Standalone gRINN Worker')
    parser.add_argument('--frontend-host', required=True,
                       help='Frontend server hostname or IP')
    parser.add_argument('--facility', default='remote-facility',
                       help='Facility identifier for this worker')
    parser.add_argument('--registration-token',
                       help='Token for worker registration (or set WORKER_REGISTRATION_TOKEN env var)')
    parser.add_argument('--storage-path', default='/data/grinn-jobs',
                       help='Path to shared storage (NFS mount point)')
    parser.add_argument('--db-password',
                       help='Database password (or set POSTGRES_PASSWORD env var)')
    parser.add_argument('--redis-password', 
                       help='Redis password (or set REDIS_PASSWORD env var)')
    parser.add_argument('--backend-port', type=int, default=8050,
                       help='Backend API port (default: 8050)')
    parser.add_argument('--grinn-image', default='grinn:latest',
                       help='gRINN Docker image name')
    parser.add_argument('--timeout', type=int, default=7200,
                       help='Job timeout in seconds (default: 2 hours)')
    parser.add_argument('--concurrency', type=int, default=2,
                       help='Number of concurrent jobs (default: 2)')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Get registration token from env if not provided
    if not args.registration_token:
        args.registration_token = os.getenv('WORKER_REGISTRATION_TOKEN')
    
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
    worker_id = setup_environment(args)
    
    # Register worker
    if args.registration_token:
        if not register_worker(args, worker_id):
            logger.error("❌ Worker registration failed")
            return 1
    
    # Run worker
    return run_worker(args, worker_id)

if __name__ == '__main__':
    sys.exit(main())