-- Migration: Create workers table for worker capacity tracking
-- Version: 001
-- Created: 2025-12-18

CREATE TABLE IF NOT EXISTS workers (
    worker_id VARCHAR(255) PRIMARY KEY,
    facility_name VARCHAR(255),
    hostname VARCHAR(255),
    max_concurrent_jobs INTEGER NOT NULL DEFAULT 2,
    current_job_count INTEGER NOT NULL DEFAULT 0,
    available_gromacs_versions TEXT,  -- JSON array of available GROMACS versions
    last_heartbeat TIMESTAMP,
    status VARCHAR(50) NOT NULL DEFAULT 'online',  -- online, offline, error
    registered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_workers_last_heartbeat ON workers(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_workers_status ON workers(status);
CREATE INDEX IF NOT EXISTS idx_workers_capacity ON workers(status, current_job_count, max_concurrent_jobs);
