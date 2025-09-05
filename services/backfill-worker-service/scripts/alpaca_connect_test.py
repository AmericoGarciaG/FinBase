#!/usr/bin/env python3
"""
Quick Alpaca connectivity test.

Reads credentials from env:
- ALPACA_API_KEY_ID
- ALPACA_SECRET_KEY
Optional:
- ALPACA_BASE_URL (overrides)
- ALPACA_PAPER (true/false; default true)
- ALPACA_DATA_FEED (iex|sip; default iex)

Performs:
1) Trading API (old SDK) get_account() against base_url (paper/live)
2) Data API (new SDK alpaca-py) fetch a tiny window of bars for AAPL

Exit code 0 on success, non-zero on failure.
"""
from __future__ import annotations

import os
import sys
import datetime as dt


def _bool_env(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> int:
    key = os.getenv("ALPACA_API_KEY_ID")
    sec = os.getenv("ALPACA_SECRET_KEY")
    if not key or not sec:
        print("[ERROR] Missing ALPACA_API_KEY_ID/ALPACA_SECRET_KEY in env", file=sys.stderr)
        return 2

    base = os.getenv("ALPACA_BASE_URL")
    if not base:
        base = "https://paper-api.alpaca.markets" if _bool_env("ALPACA_PAPER", True) else "https://api.alpaca.markets"
    # Normalize: remove trailing version suffixes (/v2, /v1)
    b = base.rstrip('/')
    if b.endswith('/v2') or b.endswith('/v1'):
        base = b.rsplit('/', 1)[0]

    print(f"Using base_url={base}")

    # 1) Trading API (old SDK)
    try:
        from alpaca_trade_api.rest import REST
        rest = REST(key_id=key, secret_key=sec, base_url=base)
        acct = rest.get_account()
        print(f"Trading API OK: account_status={acct.status}")
    except Exception as e:
        print(f"[ERROR] Trading API connection failed: {e}", file=sys.stderr)
        return 3

    # 2) Data API (new SDK)
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        from alpaca.data.enums import DataFeed, Adjustment

        client = StockHistoricalDataClient(api_key=key, secret_key=sec)
        end = dt.datetime.now(dt.timezone.utc)
        start = end - dt.timedelta(minutes=30)
        req = StockBarsRequest(
            symbol_or_symbols="AAPL",
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start,
            end=end,
            adjustment=Adjustment.RAW,
            feed=DataFeed.IEX if os.getenv("ALPACA_DATA_FEED", "iex").lower() == "iex" else DataFeed.SIP,
        )
        bars = client.get_stock_bars(req)
        count = len(bars.data.get("AAPL", [])) if getattr(bars, "data", None) else 0
        print(f"Data API OK: fetched {count} bars for AAPL (last 30m)")
    except Exception as e:
        print(f"[ERROR] Data API fetch failed: {e}", file=sys.stderr)
        return 4

    print("Alpaca connectivity test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

