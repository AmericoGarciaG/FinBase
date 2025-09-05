-- FinBase initial database schema for TimescaleDB
-- This script runs only on first initialization of the database (via Docker entrypoint)

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- for gen_random_uuid()

CREATE TABLE IF NOT EXISTS financial_data (
    "timestamp" TIMESTAMPTZ NOT NULL,
    ticker      TEXT NOT NULL,
    "open"     DOUBLE PRECISION,
    "high"     DOUBLE PRECISION,
    "low"      DOUBLE PRECISION,
    "close"    DOUBLE PRECISION,
    volume     BIGINT,
    source     TEXT,
    CONSTRAINT financial_data_pkey PRIMARY KEY ("timestamp", ticker)
);

-- Convert to hypertable on time column "timestamp"
SELECT create_hypertable('financial_data', 'timestamp', if_not_exists => TRUE);

-- Optional performance indexes (can be expanded later)
CREATE INDEX IF NOT EXISTS idx_financial_data_ticker_ts
    ON financial_data (ticker, "timestamp" DESC);

-- Master backfill jobs monitoring table (renamed from backfill_jobs)
CREATE TABLE IF NOT EXISTS master_backfill_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    error_message TEXT NULL,
    -- New fields for master job tracking
    total_sub_jobs INTEGER DEFAULT 0,
    message TEXT NULL  -- For user notifications about planning results
);

-- Sub-backfill jobs table for fragmented work
CREATE TABLE IF NOT EXISTS sub_backfill_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    master_job_id UUID NOT NULL REFERENCES master_backfill_jobs(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    error_message TEXT NULL,
    records_published BIGINT DEFAULT 0
);

-- Migrate existing data from old backfill_jobs if it exists
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'backfill_jobs') THEN
        INSERT INTO master_backfill_jobs (id, ticker, provider, start_date, end_date, status, submitted_at, started_at, completed_at, error_message, total_sub_jobs, message)
        SELECT id, ticker, provider, start_date, end_date, status, submitted_at, started_at, completed_at, error_message, 1, 'Migrated from legacy backfill_jobs'
        FROM backfill_jobs
        ON CONFLICT (id) DO NOTHING;
        
        -- Create corresponding sub-jobs for migrated master jobs
        INSERT INTO sub_backfill_jobs (master_job_id, ticker, provider, start_date, end_date, status, submitted_at, started_at, completed_at, error_message)
        SELECT id, ticker, provider, start_date, end_date, status, submitted_at, started_at, completed_at, error_message
        FROM backfill_jobs
        ON CONFLICT DO NOTHING;
        
        -- Drop old table after migration
        DROP TABLE backfill_jobs;
    END IF;
END$$;

-- Indexes for master_backfill_jobs
CREATE INDEX IF NOT EXISTS idx_master_backfill_jobs_status ON master_backfill_jobs (status);
CREATE INDEX IF NOT EXISTS idx_master_backfill_jobs_submitted_at ON master_backfill_jobs (submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_master_backfill_jobs_ticker_provider ON master_backfill_jobs (ticker, provider);

-- Indexes for sub_backfill_jobs
CREATE INDEX IF NOT EXISTS idx_sub_backfill_jobs_status ON sub_backfill_jobs (status);
CREATE INDEX IF NOT EXISTS idx_sub_backfill_jobs_master_id ON sub_backfill_jobs (master_job_id);
CREATE INDEX IF NOT EXISTS idx_sub_backfill_jobs_ticker_provider ON sub_backfill_jobs (ticker, provider);
CREATE INDEX IF NOT EXISTS idx_sub_backfill_jobs_date_range ON sub_backfill_jobs (ticker, provider, start_date, end_date);

-- Provider reputation table for intelligent provider selection and scoring
CREATE TABLE IF NOT EXISTS provider_reputation (
    provider_name TEXT PRIMARY KEY,
    total_requests BIGINT DEFAULT 0,
    successful_requests BIGINT DEFAULT 0,
    failed_requests BIGINT DEFAULT 0,
    data_quality_issues BIGINT DEFAULT 0,
    total_records_published BIGINT DEFAULT 0,
    last_seen_active TIMESTAMPTZ NULL
);
