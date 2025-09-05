"""Provider utilities for fetching historical data via Alpaca (alpaca-trade-api).

Exports fetch_alpaca for backfill-worker-service.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable



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


def _generate_synthetic_daily(ticker: str, start_date: str, end_date: str):
    start = datetime.fromisoformat(start_date + "T00:00:00+00:00").astimezone(timezone.utc)
    end = datetime.fromisoformat(end_date + "T00:00:00+00:00").astimezone(timezone.utc)
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
                "provider": "alpaca",
                "granularity": "1d",
            },
        }


def _map_interval(interval: str) -> str:
    """Map interval to alpaca-trade-api timeframe strings (e.g., '1Min','1Hour','1Day')."""
    interval = (interval or "1d").lower()
    if interval in ("1d", "1day", "day"):
        return "1Day"
    if interval in ("1h", "1hour", "hour"):
        return "1Hour"
    if interval in ("1m", "1min", "minute"):
        return "1Min"
    return "1Day"


def fetch_alpaca(*,
                 ticker: str,
                 start_date: str,
                 end_date: str,
                 interval: str = "1d",
                 chunk_months: int = 1,
                 sleep_between_chunks_s: float = 0.2) -> Iterable[Dict]:
    """
    Fetch historical candles from Alpaca in month-sized chunks using alpaca-trade-api.

    Requires env: ALPACA_API_KEY_ID, ALPACA_SECRET_KEY
    Optional env: ALPACA_BASE_URL (defaults to https://paper-api.alpaca.markets for auth; data endpoint is handled by SDK)
    """
    # Defer import to runtime to avoid hard dependency at module import time
    try:
        from alpaca_trade_api.rest import REST
    except Exception as e:
        raise RuntimeError(f"Alpaca provider unavailable: failed to import alpaca-trade-api: {e}")

    # Synthetic path for test tickers
    if ticker.upper().startswith("TEST."):
        yield from _generate_synthetic_daily(ticker, start_date, end_date)
        return

    api_key = os.getenv("ALPACA_API_KEY_ID") or os.getenv("ALPACA_KEY_ID")
    api_secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_SECRET")
    # Determine base_url: prefer ALPACA_BASE_URL; otherwise ALPACA_PAPER=true -> paper endpoint; else live
    env_base = os.getenv("ALPACA_BASE_URL")
    if env_base:
        base_url = env_base
    else:
        paper_flag = (os.getenv("ALPACA_PAPER", "true").strip().lower() in ("1", "true", "yes", "y"))
        base_url = "https://paper-api.alpaca.markets" if paper_flag else "https://api.alpaca.markets"

    if not api_key or not api_secret:
        raise RuntimeError("Missing Alpaca credentials in environment (ALPACA_API_KEY_ID/ALPACA_SECRET_KEY)")

    client = REST(key_id=api_key, secret_key=api_secret, base_url=base_url)

    # Normalize to UTC date boundaries [start, end)
    start = datetime.fromisoformat(start_date + "T00:00:00+00:00").astimezone(timezone.utc)
    end = datetime.fromisoformat(end_date + "T00:00:00+00:00").astimezone(timezone.utc)

    if start >= end:
        return []

    cur = _month_start(start)
    last = _month_start(end)

    tf = _map_interval(interval)

    # Use free feed if available
    feed = os.getenv("ALPACA_DATA_FEED", "iex")
    adjustment = os.getenv("ALPACA_ADJUSTMENT", "raw")

    while cur <= last:
        nxt = _add_months(cur, chunk_months)
        chunk_start = max(cur, start)
        chunk_end = min(nxt, end)
        if chunk_start >= chunk_end:
            cur = nxt
            continue

        try:
            # Request bars; some versions return DataFrame directly, others BarSet with .df
            bars = client.get_bars(
                symbol=ticker,
                timeframe=tf,
                start=chunk_start.isoformat(),
                end=chunk_end.isoformat(),
                adjustment=adjustment,
                feed=feed,
            )

            # Try DataFrame path first (or treat bars as DF if it quacks like one)
            df = getattr(bars, "df", bars)
            if hasattr(df, "iterrows") and getattr(df, "empty", False) is False:
                # If multi-index (symbol, time), select only this ticker
                if hasattr(df.index, "names") and len(df.index.names) == 2:
                    try:
                        sub = df.xs(ticker)
                    except Exception:
                        sub = df
                else:
                    sub = df
                for idx, row in sub.iterrows():
                    if hasattr(idx, "to_pydatetime"):
                        dt = idx.to_pydatetime()
                    else:
                        # If index is timestamp-like
                        try:
                            dt = datetime.fromtimestamp(idx.timestamp(), tz=timezone.utc)
                        except Exception:
                            dt = datetime.fromisoformat(str(idx)).replace(tzinfo=timezone.utc)
                    yield {
                        "ticker_symbol": ticker,
                        "timestamp_utc": _iso_utc(dt, ms=False),
                        "open": float(row["open"]) if "open" in row else float(row.get("Open", 0.0)),
                        "high": float(row["high"]) if "high" in row else float(row.get("High", 0.0)),
                        "low": float(row["low"]) if "low" in row else float(row.get("Low", 0.0)),
                        "close": float(row["close"]) if "close" in row else float(row.get("Close", 0.0)),
                        "volume": int(row["volume"]) if "volume" in row else int(row.get("Volume", 0)) if row.get("Volume", 0) == row.get("Volume", 0) else 0,
                        "metadata": {
                            "source": "alpaca",
                            "provider": "alpaca",
                            "granularity": interval,
                            "feed": feed,
                        },
                    }
            else:
                # Fallback: bars.iterate over Bar objects
                try:
                    iter_bars = list(bars)
                except TypeError:
                    # If bars is iterable already
                    iter_bars = bars
                for b in iter_bars:
                    # Expect fields: b.t (datetime), b.o, b.h, b.l, b.c, b.v
                    dt = getattr(b, "t", None)
                    if dt is None:
                        # Try timestamp or parse
                        dt = datetime.fromisoformat(getattr(b, "Timestamp", getattr(b, "timestamp", str(chunk_start))))
                    if isinstance(dt, str):
                        try:
                            dt = datetime.fromisoformat(dt)
                        except Exception:
                            dt = chunk_start
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    yield {
                        "ticker_symbol": ticker,
                        "timestamp_utc": _iso_utc(dt, ms=False),
                        "open": float(getattr(b, "o", getattr(b, "open", 0.0))),
                        "high": float(getattr(b, "h", getattr(b, "high", 0.0))),
                        "low": float(getattr(b, "l", getattr(b, "low", 0.0))),
                        "close": float(getattr(b, "c", getattr(b, "close", 0.0))),
                        "volume": int(getattr(b, "v", getattr(b, "volume", 0)) or 0),
                        "metadata": {
                            "source": "alpaca",
                            "provider": "alpaca",
                            "granularity": interval,
                            "feed": feed,
                        },
                    }
        except Exception:
            # Fallback to alpaca-py new SDK
            try:
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockBarsRequest
                from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
                from alpaca.data.enums import Adjustment as PyAdjustment, DataFeed as PyDataFeed
            except Exception as e2:
                raise RuntimeError(f"Alpaca provider unavailable: failed to import alpaca-py: {e2}")

            hist_client = StockHistoricalDataClient(api_key=api_key, secret_key=api_secret)
            # Map interval to TimeFrame
            unit = TimeFrameUnit.Minute
            amount = 1
            if interval.lower().startswith('1h') or interval.lower().startswith('1hour') or interval.lower().startswith('hour'):
                unit = TimeFrameUnit.Hour
            elif interval.lower().startswith('1d') or interval.lower().startswith('1day') or interval.lower().startswith('day'):
                unit = TimeFrameUnit.Day
            tf_py = TimeFrame(amount, unit)

            req = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=tf_py,
                start=chunk_start,
                end=chunk_end,
                adjustment=PyAdjustment.RAW,
                feed=PyDataFeed.IEX if (feed or '').lower() == 'iex' else PyDataFeed.SIP,
            )
            bars_response = hist_client.get_stock_bars(req)
            series = []
            try:
                series = bars_response.data.get(ticker, [])
            except Exception:
                # Different versions expose .data or direct iterable
                series = getattr(bars_response, 'data', []) or list(bars_response) if bars_response else []

            for bar in series:
                ts = getattr(bar, 'timestamp', None) or getattr(bar, 't', None)
                if isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts)
                    except Exception:
                        dt = chunk_start
                else:
                    dt = ts or chunk_start
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                yield {
                    "ticker_symbol": ticker,
                    "timestamp_utc": _iso_utc(dt, ms=False),
                    "open": float(getattr(bar, 'open', getattr(bar, 'o', 0.0))),
                    "high": float(getattr(bar, 'high', getattr(bar, 'h', 0.0))),
                    "low": float(getattr(bar, 'low', getattr(bar, 'l', 0.0))),
                    "close": float(getattr(bar, 'close', getattr(bar, 'c', 0.0))),
                    "volume": int(getattr(bar, 'volume', getattr(bar, 'v', 0)) or 0),
                    "metadata": {
                        "source": "alpaca",
                        "provider": "alpaca",
                        "granularity": interval,
                        "feed": feed,
                    },
                }
        else:
            # Fallback: bars.iterate over Bar objects
            try:
                iter_bars = list(bars)
            except TypeError:
                # If bars is iterable already
                iter_bars = bars
            for b in iter_bars:
                # Expect fields: b.t (datetime), b.o, b.h, b.l, b.c, b.v
                dt = getattr(b, "t", None)
                if dt is None:
                    # Try timestamp or parse
                    dt = datetime.fromisoformat(getattr(b, "Timestamp", getattr(b, "timestamp", str(chunk_start))))
                if isinstance(dt, str):
                    try:
                        dt = datetime.fromisoformat(dt)
                    except Exception:
                        dt = chunk_start
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                yield {
                    "ticker_symbol": ticker,
                    "timestamp_utc": _iso_utc(dt, ms=False),
                    "open": float(getattr(b, "o", getattr(b, "open", 0.0))),
                    "high": float(getattr(b, "h", getattr(b, "high", 0.0))),
                    "low": float(getattr(b, "l", getattr(b, "low", 0.0))),
                    "close": float(getattr(b, "c", getattr(b, "close", 0.0))),
                    "volume": int(getattr(b, "v", getattr(b, "volume", 0)) or 0),
                    "metadata": {
                        "source": "alpaca",
                        "provider": "alpaca",
                        "granularity": interval,
                        "feed": feed,
                    },
                }

        time.sleep(max(0.0, sleep_between_chunks_s))
        cur = nxt
