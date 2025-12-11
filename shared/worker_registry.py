"""
Worker Registry for gRINN Web Service.
Manages worker registration, authentication, and health monitoring using Redis.
"""

import os
import secrets
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import json

logger = logging.getLogger(__name__)


class WorkerRegistry:
    """
    Manages distributed worker registration and health monitoring.
    
    Workers must authenticate with a token before being allowed to process jobs.
    The registry tracks:
    - Registered workers and their capabilities
    - Worker heartbeats for health monitoring
    - Active/inactive worker status
    
    Redis keys used:
    - grinn:workers:{worker_id} - Worker info hash
    - grinn:workers:list - Set of all worker IDs
    - grinn:workers:active - Set of active worker IDs (recent heartbeat)
    """
    
    # Redis key prefixes
    WORKER_PREFIX = "grinn:workers:"
    WORKER_LIST_KEY = "grinn:workers:list"
    WORKER_ACTIVE_KEY = "grinn:workers:active"
    
    # Heartbeat timeout (seconds) - worker considered inactive if no heartbeat
    HEARTBEAT_TIMEOUT = 120  # 2 minutes
    
    # Worker info expiry (seconds) - worker info removed if no activity
    WORKER_EXPIRY = 86400  # 24 hours
    
    def __init__(self, redis_client, registration_token: Optional[str] = None):
        """
        Initialize the worker registry.
        
        Args:
            redis_client: Redis client instance
            registration_token: Token required for worker registration.
                              If not provided, uses WORKER_REGISTRATION_TOKEN env var.
        """
        self.redis = redis_client
        
        # Get registration token from parameter or environment
        self.registration_token = registration_token or os.environ.get(
            "WORKER_REGISTRATION_TOKEN"
        )
        
        if not self.registration_token:
            logger.warning(
                "No WORKER_REGISTRATION_TOKEN configured. "
                "Worker registration will be disabled."
            )
        
        logger.info("WorkerRegistry initialized")
    
    def _hash_token(self, token: str) -> str:
        """Hash a token for secure comparison."""
        return hashlib.sha256(token.encode()).hexdigest()
    
    def validate_token(self, token: str) -> bool:
        """
        Validate a worker registration token.
        
        Args:
            token: Token provided by worker
            
        Returns:
            True if token is valid
        """
        if not self.registration_token:
            logger.warning("No registration token configured, rejecting registration")
            return False
        
        # Constant-time comparison to prevent timing attacks
        return secrets.compare_digest(token, self.registration_token)
    
    def register_worker(
        self,
        token: str,
        worker_id: str,
        facility: str,
        capabilities: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Register a new worker with the system.
        
        Args:
            token: Registration token for authentication
            worker_id: Unique identifier for the worker
            facility: Facility/site name where worker is located
            capabilities: Worker capabilities (cpu_cores, memory_gb, gpu, etc.)
            metadata: Additional worker metadata (hostname, version, etc.)
            
        Returns:
            Dict with registration status and worker info
            
        Raises:
            PermissionError: If token is invalid
            ValueError: If worker_id is invalid
        """
        # Validate token
        if not self.validate_token(token):
            logger.warning(f"Invalid registration token for worker {worker_id}")
            raise PermissionError("Invalid registration token")
        
        if not worker_id or not worker_id.strip():
            raise ValueError("Worker ID is required")
        
        worker_id = worker_id.strip()
        
        # Prepare worker info
        now = datetime.now(timezone.utc)
        worker_info = {
            "worker_id": worker_id,
            "facility": facility,
            "capabilities": json.dumps(capabilities or {}),
            "metadata": json.dumps(metadata or {}),
            "registered_at": now.isoformat(),
            "last_heartbeat": now.isoformat(),
            "status": "active",
            "jobs_completed": 0,
            "jobs_failed": 0,
            "current_job": ""
        }
        
        # Store in Redis
        worker_key = f"{self.WORKER_PREFIX}{worker_id}"
        self.redis.hset(worker_key, mapping=worker_info)
        self.redis.expire(worker_key, self.WORKER_EXPIRY)
        
        # Add to worker lists
        self.redis.sadd(self.WORKER_LIST_KEY, worker_id)
        self.redis.sadd(self.WORKER_ACTIVE_KEY, worker_id)
        
        logger.info(f"Worker registered: {worker_id} at facility {facility}")
        
        return {
            "status": "registered",
            "worker_id": worker_id,
            "facility": facility,
            "registered_at": now.isoformat()
        }
    
    def heartbeat(
        self,
        worker_id: str,
        current_job: Optional[str] = None,
        status: str = "active"
    ) -> bool:
        """
        Update worker heartbeat to indicate it's still alive.
        
        Args:
            worker_id: Worker identifier
            current_job: ID of job currently being processed (if any)
            status: Worker status (active, busy, idle)
            
        Returns:
            True if heartbeat recorded successfully
        """
        worker_key = f"{self.WORKER_PREFIX}{worker_id}"
        
        # Check if worker exists
        if not self.redis.exists(worker_key):
            logger.warning(f"Heartbeat from unregistered worker: {worker_id}")
            return False
        
        # Update heartbeat and status
        now = datetime.now(timezone.utc)
        updates = {
            "last_heartbeat": now.isoformat(),
            "status": status
        }
        
        if current_job is not None:
            updates["current_job"] = current_job
        
        self.redis.hset(worker_key, mapping=updates)
        self.redis.expire(worker_key, self.WORKER_EXPIRY)
        
        # Add to active set
        self.redis.sadd(self.WORKER_ACTIVE_KEY, worker_id)
        
        return True
    
    def get_worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific worker.
        
        Args:
            worker_id: Worker identifier
            
        Returns:
            Worker info dict or None if not found
        """
        worker_key = f"{self.WORKER_PREFIX}{worker_id}"
        worker_data = self.redis.hgetall(worker_key)
        
        if not worker_data:
            return None
        
        # Decode Redis bytes to strings
        worker_info = {
            k.decode() if isinstance(k, bytes) else k: 
            v.decode() if isinstance(v, bytes) else v 
            for k, v in worker_data.items()
        }
        
        # Parse JSON fields
        for field in ["capabilities", "metadata"]:
            if field in worker_info:
                try:
                    worker_info[field] = json.loads(worker_info[field])
                except (json.JSONDecodeError, TypeError):
                    worker_info[field] = {}
        
        # Parse integer fields
        for field in ["jobs_completed", "jobs_failed"]:
            if field in worker_info:
                try:
                    worker_info[field] = int(worker_info[field])
                except (ValueError, TypeError):
                    worker_info[field] = 0
        
        # Check if worker is active based on heartbeat
        if "last_heartbeat" in worker_info:
            try:
                last_hb = datetime.fromisoformat(worker_info["last_heartbeat"])
                if last_hb.tzinfo is None:
                    last_hb = last_hb.replace(tzinfo=timezone.utc)
                
                timeout = datetime.now(timezone.utc) - timedelta(seconds=self.HEARTBEAT_TIMEOUT)
                worker_info["is_active"] = last_hb > timeout
            except (ValueError, TypeError):
                worker_info["is_active"] = False
        else:
            worker_info["is_active"] = False
        
        return worker_info
    
    def get_active_workers(self) -> List[Dict[str, Any]]:
        """
        Get list of all active workers (recent heartbeat).
        
        Returns:
            List of worker info dicts
        """
        # First, clean up inactive workers from active set
        self._cleanup_inactive_workers()
        
        active_ids = self.redis.smembers(self.WORKER_ACTIVE_KEY)
        workers = []
        
        for worker_id in active_ids:
            if isinstance(worker_id, bytes):
                worker_id = worker_id.decode()
            
            worker_info = self.get_worker(worker_id)
            if worker_info and worker_info.get("is_active", False):
                workers.append(worker_info)
        
        return workers
    
    def get_all_workers(self) -> List[Dict[str, Any]]:
        """
        Get list of all registered workers (active and inactive).
        
        Returns:
            List of worker info dicts
        """
        worker_ids = self.redis.smembers(self.WORKER_LIST_KEY)
        workers = []
        
        for worker_id in worker_ids:
            if isinstance(worker_id, bytes):
                worker_id = worker_id.decode()
            
            worker_info = self.get_worker(worker_id)
            if worker_info:
                workers.append(worker_info)
        
        return workers
    
    def get_workers_by_facility(self, facility: str) -> List[Dict[str, Any]]:
        """
        Get all workers at a specific facility.
        
        Args:
            facility: Facility name to filter by
            
        Returns:
            List of worker info dicts at the facility
        """
        all_workers = self.get_all_workers()
        return [w for w in all_workers if w.get("facility") == facility]
    
    def deregister_worker(self, worker_id: str) -> bool:
        """
        Remove a worker from the registry.
        
        Args:
            worker_id: Worker identifier
            
        Returns:
            True if worker was removed
        """
        worker_key = f"{self.WORKER_PREFIX}{worker_id}"
        
        # Remove from Redis
        self.redis.delete(worker_key)
        self.redis.srem(self.WORKER_LIST_KEY, worker_id)
        self.redis.srem(self.WORKER_ACTIVE_KEY, worker_id)
        
        logger.info(f"Worker deregistered: {worker_id}")
        return True
    
    def update_job_stats(
        self,
        worker_id: str,
        job_completed: bool = True,
        current_job: str = ""
    ):
        """
        Update worker job statistics.
        
        Args:
            worker_id: Worker identifier
            job_completed: True if job completed successfully, False if failed
            current_job: ID of current job (empty if idle)
        """
        worker_key = f"{self.WORKER_PREFIX}{worker_id}"
        
        if not self.redis.exists(worker_key):
            return
        
        if job_completed:
            self.redis.hincrby(worker_key, "jobs_completed", 1)
        else:
            self.redis.hincrby(worker_key, "jobs_failed", 1)
        
        self.redis.hset(worker_key, "current_job", current_job)
    
    def _cleanup_inactive_workers(self):
        """Remove workers with stale heartbeats from active set."""
        timeout = datetime.now(timezone.utc) - timedelta(seconds=self.HEARTBEAT_TIMEOUT)
        
        active_ids = self.redis.smembers(self.WORKER_ACTIVE_KEY)
        
        for worker_id in active_ids:
            if isinstance(worker_id, bytes):
                worker_id = worker_id.decode()
            
            worker_key = f"{self.WORKER_PREFIX}{worker_id}"
            last_hb = self.redis.hget(worker_key, "last_heartbeat")
            
            if last_hb:
                if isinstance(last_hb, bytes):
                    last_hb = last_hb.decode()
                try:
                    hb_time = datetime.fromisoformat(last_hb)
                    if hb_time.tzinfo is None:
                        hb_time = hb_time.replace(tzinfo=timezone.utc)
                    
                    if hb_time < timeout:
                        self.redis.srem(self.WORKER_ACTIVE_KEY, worker_id)
                        self.redis.hset(worker_key, "status", "inactive")
                except (ValueError, TypeError):
                    pass
            else:
                # No heartbeat recorded, remove from active
                self.redis.srem(self.WORKER_ACTIVE_KEY, worker_id)
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """
        Get overall registry statistics.
        
        Returns:
            Dict with registry stats
        """
        self._cleanup_inactive_workers()
        
        total_workers = self.redis.scard(self.WORKER_LIST_KEY)
        active_workers = self.redis.scard(self.WORKER_ACTIVE_KEY)
        
        # Get workers grouped by facility
        all_workers = self.get_all_workers()
        facilities = {}
        total_completed = 0
        total_failed = 0
        
        for worker in all_workers:
            facility = worker.get("facility", "unknown")
            if facility not in facilities:
                facilities[facility] = {"total": 0, "active": 0}
            facilities[facility]["total"] += 1
            if worker.get("is_active", False):
                facilities[facility]["active"] += 1
            
            total_completed += worker.get("jobs_completed", 0)
            total_failed += worker.get("jobs_failed", 0)
        
        return {
            "total_workers": total_workers,
            "active_workers": active_workers,
            "inactive_workers": total_workers - active_workers,
            "facilities": facilities,
            "total_jobs_completed": total_completed,
            "total_jobs_failed": total_failed,
            "heartbeat_timeout_seconds": self.HEARTBEAT_TIMEOUT
        }


# Global worker registry instance
_worker_registry: Optional[WorkerRegistry] = None


def get_worker_registry(redis_client=None) -> WorkerRegistry:
    """
    Get the global worker registry instance.
    
    Args:
        redis_client: Redis client instance (required for first call)
        
    Returns:
        WorkerRegistry instance
    """
    global _worker_registry
    
    if _worker_registry is None:
        if redis_client is None:
            raise ValueError("Redis client required for WorkerRegistry initialization")
        _worker_registry = WorkerRegistry(redis_client)
    
    return _worker_registry


def reset_worker_registry():
    """Reset the global worker registry instance (useful for testing)."""
    global _worker_registry
    _worker_registry = None


def generate_registration_token() -> str:
    """
    Generate a secure registration token.
    
    Returns:
        A cryptographically secure random token string
    """
    return secrets.token_urlsafe(32)
