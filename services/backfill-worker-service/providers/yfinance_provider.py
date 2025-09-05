"""Provider utilities for fetching historical data via yfinance.

Exports fetch_yfinance for backfill-worker-service.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

import yfinance as yf


def _iso_utc(dt: datetime, ms: bool = False) -> str:
    """Return an ISO 8601 UTC timestamp string with a trailing 'Z'.

    Args:
        dt: A naive or timezone-aware datetime instance.
        ms: When True, include millisecond precision; otherwise, seconds.

    Returns:
        The UTC timestamp in ISO-8601 format, using 'Z' instead of '+00:00'.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="milliseconds" if ms else "seconds").replace("+00:00", "Z")


def _month_start(dt: datetime) -> datetime:
    """Return the first instant (00:00Z) of the month for the given datetime.

    The result is always timezone-aware in UTC.
    """
    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)


def _add_months(dt: datetime, months: int) -> datetime:
    """Return the first day of the month that is 'months' after the given datetime.

    Keeps the day anchored to the 1st and sets timezone to UTC.
    """
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    return datetime(y, m, 1, tzinfo=timezone.utc)


def _generate_synthetic_daily(ticker: str, start_date: str, end_date: str) -> Iterable[Dict]:
    """Generate deterministic synthetic daily candles inclusive of end_date.

    Used for test tickers like 'TEST.*' to ensure isolated and repeatable e2e.
    """
    start = datetime.fromisoformat(start_date + "T00:00:00+00:00").astimezone(timezone.utc)
    end = datetime.fromisoformat(end_date + "T00:00:00+00:00").astimezone(timezone.utc)
    # Inclusive of end day
    days = int((end - start).days) + 1
    if days <= 0:
        return []
    base = 100.0
    for i in range(days):
        dt = start + timedelta(days=i)
        o = base + i
        h = o + 2.0
        l = o - 2.0
        c = o + 1.0
        v = 1000 + i
        yield {
            "ticker_symbol": ticker,
            "timestamp_utc": _iso_utc(dt, ms=False),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "metadata": {
                "source": "synthetic",
                "provider": "yfinance",
                "granularity": "1d",
            },
        }


def fetch_yfinance(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    interval: str = "1d",
    chunk_months: int = 1,
    sleep_between_chunks_s: float = 0.2,
) -> Iterable[Dict]:
    """
    Fetch historical candles from yfinance in month-sized chunks.

    Behavior:
    - Uses inclusive [start_date, end_date] at 00:00Z boundaries.
    - Emits canonical FinBase records for each bar.
    - For synthetic test tickers with prefix 'TEST.', generates deterministic daily data
      inclusive of end_date for stable end-to-end tests (no external calls).

    Args:
        ticker: Ticker symbol, e.g. 'AAPL'.
        start_date: Inclusive start date in YYYY-MM-DD (UTC).
        end_date: Inclusive end date in YYYY-MM-DD (UTC).
        interval: Requested granularity (e.g., '1d', '1h', '1m').
        chunk_months: Number of months per request chunk to yfinance.
        sleep_between_chunks_s: Sleep between chunks to be polite with remote API.

    Yields:
        dict: Canonical FinBase record per candle/bar.
    """
    # Synthetic data path for test tickers
    if ticker.upper().startswith("TEST."):
        yield from _generate_synthetic_daily(ticker, start_date, end_date)
        return

    # Normalize bounds to UTC 00:00:00 -> [start, end)
    start = datetime.fromisoformat(start_date + "T00:00:00+00:00").astimezone(timezone.utc)
    end = datetime.fromisoformat(end_date + "T00:00:00+00:00").astimezone(timezone.utc)

    if start >= end:
        return []

    # Align to month starts for chunking
    cur = _month_start(start)
    last = _month_start(end)

    t = yf.Ticker(ticker)

    while cur <= last:
        nxt = _add_months(cur, chunk_months)
        # yfinance: 'end' is exclusive
        chunk_start = max(cur, start)
        chunk_end = min(nxt, end)
        if chunk_start >= chunk_end:
            cur = nxt
            continue

        df = t.history(start=chunk_start, end=chunk_end, interval=interval, auto_adjust=False, prepost=False, repair=True)
        if df is not None and not df.empty:
            for idx, row in df.iterrows():
                if hasattr(idx, "to_pydatetime"):
                    dt = idx.to_pydatetime()
                else:
                    dt = datetime.fromtimestamp(idx.timestamp(), tz=timezone.utc)
                yield {
                    "ticker_symbol": ticker,
                    "timestamp_utc": _iso_utc(dt, ms=False),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]) if not (row["Volume"] != row["Volume"]) else 0,
                    "metadata": {
                        "source": "yfinance",
                        "provider": "yfinance",
                        "granularity": interval,
                    },
                }
        time.sleep(max(0.0, sleep_between_chunks_s))
        cur = nxt

