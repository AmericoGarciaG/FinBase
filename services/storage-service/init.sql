-- FinBase initial database schema for TimescaleDB
-- This script runs only on first initialization of the database (via Docker entrypoint)

CREATE EXTENSION IF NOT EXISTS timescaledb;

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

