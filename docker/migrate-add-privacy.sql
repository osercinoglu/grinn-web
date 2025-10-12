-- Migration script to add privacy column to existing gRINN web databases
-- Run this script if you have an existing database without the is_private column

-- Add is_private column to jobs table
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_private BOOLEAN DEFAULT FALSE NOT NULL;

-- Update existing jobs to be public by default (already the default value)
UPDATE jobs SET is_private = FALSE WHERE is_private IS NULL;

-- Add index for better performance on privacy queries
CREATE INDEX IF NOT EXISTS idx_jobs_is_private ON jobs(is_private);

-- Display migration status
SELECT 'Migration completed: is_private column added to jobs table' as status;