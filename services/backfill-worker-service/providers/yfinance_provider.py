from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

import yfinance as yf


def _iso_utc(dt: datetime, ms: bool = False) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="milliseconds" if ms else "seconds").replace("+00:00", "Z")


def _month_start(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)


def _add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    return datetime(y, m, 1, tzinfo=timezone.utc)


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
    Fetch historical candles from yfinance in monthly chunks (configurable).

    Notes:
    - yfinance no soporta 1m para rangos muy antiguos; para grandes rangos
      se recomienda interval="1d" o más grueso.
    - Devuelve registros en formato canónico FinBase.
    """
    # Normaliza límites a UTC 00:00:00 -> [start, end)
    start = datetime.fromisoformat(start_date + "T00:00:00+00:00").astimezone(timezone.utc)
    end = datetime.fromisoformat(end_date + "T00:00:00+00:00").astimezone(timezone.utc)

    if start >= end:
        return []

    # Alinea a inicios de mes para chunking
    cur = _month_start(start)
    last = _month_start(end)

    t = yf.Ticker(ticker)

    while cur <= last:
        nxt = _add_months(cur, chunk_months)
        # yfinance: end es exclusivo
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
                        "granularity": interval,
                    },
                }
        time.sleep(max(0.0, sleep_between_chunks_s))
        cur = nxt

