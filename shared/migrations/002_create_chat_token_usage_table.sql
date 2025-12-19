-- Migration: Create chat_token_usage table for per-job token tracking
-- Version: 002
-- Created: 2025-12-18

CREATE TABLE IF NOT EXISTS chat_token_usage (
    job_id VARCHAR(255) PRIMARY KEY,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    token_limit INTEGER NOT NULL DEFAULT 100000,
    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_token_usage_job_id ON chat_token_usage(job_id);
CREATE INDEX IF NOT EXISTS idx_chat_token_usage_updated ON chat_token_usage(last_updated);
