#!/usr/bin/env python3
"""
FinBase API Service (read-only)

FastAPI + asyncpg service providing historical data from TimescaleDB.
Exposes: GET /v1/data/history/{ticker}

Key features:
- Async connection pool (created on startup, closed on shutdown)
- Input validation with Pydantic v2
- Time-series aggregation in DB using time_bucket for 1hour/1day intervals
- Clean JSON responses and robust error handling
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Annotated, Literal, Optional

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator

# Load environment from .env if present
load_dotenv()

app = FastAPI(title="FinBase API", version="0.1.0")


class Interval(BaseModel):
    value: Literal["1min", "1hour", "1day"]

    @property
    def bucket(self) -> Optional[timedelta]:
        if self.value == "1min":
            return None  # no aggregation
        return {"1hour": timedelta(hours=1), "1day": timedelta(days=1)}[self.value]


class HistoryQuery(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    interval: Interval
    limit: int = 1000

    @field_validator("limit")
    @classmethod
    def _limit_bounds(cls, v: int) -> int:
        if v <= 0 or v > 10000:
            raise ValueError("limit must be between 1 and 10000")
        return v

    @field_validator("end_date")
    @classmethod
    def _check_range(cls, v: Optional[datetime], info):
        # The Pydantic v2 validator gets only one field at a time; cross-field check below in model-level validation
        return v

    @field_validator("start_date")
    @classmethod
    def _check_start(cls, v: Optional[datetime], info):
        return v

    def validate_range(self) -> None:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be <= end_date")


class Candle(BaseModel):
    timestamp: datetime
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None


class HistoryResponse(BaseModel):
    ticker: str
    interval: str
    count: int
    data: list[Candle]


async def _make_pool() -> asyncpg.Pool:
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    db = os.getenv("DB_NAME", "finbase")
    user = os.getenv("DB_USER", "finbase")
    password = os.getenv("DB_PASSWORD", "supersecretpassword")

    min_size = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
    max_size = int(os.getenv("DB_POOL_MAX_SIZE", "10"))

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size, command_timeout=60)


@app.on_event("startup")
async def on_startup():
    app.state.pool = await _make_pool()


@app.on_event("shutdown")
async def on_shutdown():
    pool: asyncpg.Pool = app.state.pool
    if pool:
        await pool.close()


@app.get("/v1/data/history/{ticker}", response_model=HistoryResponse)
async def get_history(
    ticker: str,
    start_date: Optional[datetime] = Query(default=None, description="ISO date/time (UTC) inclusive lower bound"),
    end_date: Optional[datetime] = Query(default=None, description="ISO date/time (UTC) inclusive upper bound"),
    interval: Literal["1min", "1hour", "1day"] = Query(default="1min", description="Aggregation interval"),
    limit: int = Query(default=1000, ge=1, le=10000, description="Max rows to return"),
):
    # Validate inputs using Pydantic model (including cross-field checks)
    q = HistoryQuery(start_date=start_date, end_date=end_date, interval=Interval(value=interval), limit=limit)
    try:
        q.validate_range()
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    pool: asyncpg.Pool = app.state.pool

    if q.interval.bucket is None:
        # No aggregation: 1-minute granularity (direct rows)
        sql = (
            "SELECT \"timestamp\" AS ts, open, high, low, close, volume\n"
            "FROM financial_data\n"
            "WHERE ticker = $1\n"
            "  AND ($2::timestamptz IS NULL OR \"timestamp\" >= $2)\n"
            "  AND ($3::timestamptz IS NULL OR \"timestamp\" <= $3)\n"
            "ORDER BY ts ASC\n"
            "LIMIT $4"
        )
        params = (ticker, q.start_date, q.end_date, q.limit)
    else:
        # Aggregation with time_bucket in DB
        sql = (
            "WITH filt AS (\n"
            "  SELECT \"timestamp\", open, high, low, close, volume\n"
            "  FROM financial_data\n"
            "  WHERE ticker = $1\n"
            "    AND ($2::timestamptz IS NULL OR \"timestamp\" >= $2)\n"
            "    AND ($3::timestamptz IS NULL OR \"timestamp\" <= $3)\n"
            ")\n"
            "SELECT\n"
            "  time_bucket($4::interval, \"timestamp\") AS ts,\n"
            "  (ARRAY_AGG(open  ORDER BY \"timestamp\" ASC))[1]   AS open,\n"
            "  MAX(high)                                         AS high,\n"
            "  MIN(low)                                          AS low,\n"
            "  (ARRAY_AGG(close ORDER BY \"timestamp\" DESC))[1]  AS close,\n"
            "  SUM(volume)                                       AS volume\n"
            "FROM filt\n"
            "GROUP BY ts\n"
            "ORDER BY ts ASC\n"
            "LIMIT $5"
        )
        params = (ticker, q.start_date, q.end_date, q.interval.bucket, q.limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    if not rows:
        raise HTTPException(status_code=404, detail="Ticker not found or no data in the requested range")

    data = [
        Candle(
            timestamp=row["ts"],
            open=row.get("open"),
            high=row.get("high"),
            low=row.get("low"),
            close=row.get("close"),
            volume=row.get("volume"),
        )
        for row in rows
    ]
    return HistoryResponse(ticker=ticker.upper(), interval=q.interval.value, count=len(data), data=data)

