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

-- Backfill jobs monitoring table
CREATE TABLE IF NOT EXISTS backfill_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    error_message TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_backfill_jobs_status ON backfill_jobs (status);
CREATE INDEX IF NOT EXISTS idx_backfill_jobs_submitted_at ON backfill_jobs (submitted_at DESC);
