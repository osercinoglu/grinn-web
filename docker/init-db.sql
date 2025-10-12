-- Initialize gRINN Web Database
-- This script is automatically executed when the PostgreSQL container starts

-- Ensure the database exists (already created by POSTGRES_DB)
\c grinn_web;

-- Grant additional permissions
GRANT ALL ON SCHEMA public TO grinn_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO grinn_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO grinn_user;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO grinn_user;

-- Create extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- The actual tables will be created by SQLAlchemy when the application starts