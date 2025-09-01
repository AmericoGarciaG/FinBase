"""
Validation rules for FinBase quality-service.

This module defines the validation logic for incoming canonical data messages
consumed from raw_data_queue. It exposes a single entrypoint:

    validate_data(data) -> tuple[bool, Optional[str]]

Returns (True, None) when the payload is valid, otherwise (False, "reason").
"""
from __future__ import annotations

from typing import Optional, Tuple, Any
import math


RequiredFields = (
    "ticker_symbol",
    "timestamp_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
)


def _is_number(x: Any) -> bool:
    """Return True if x is a finite number (int or float), excluding booleans)."""
    if isinstance(x, bool):
        return False
    if isinstance(x, (int, float)):
        return math.isfinite(float(x))
    return False


def validate_data(data: Any) -> Tuple[bool, Optional[str]]:
    """
    Validate the canonical payload according to initial rule set.

    Rules implemented:
    1) Structural integrity: presence and non-null of core fields
    2) OHLC coherence: high is the max, low is the min (relative to open/close)
       - high >= open, high >= close, low <= open, low <= close, and high >= low
    3) Non-negative values: open, high, low, close, volume >= 0

    Args:
        data: Decoded JSON object expected to be a dict

    Returns:
        (is_valid, reason) where reason is None when valid.
    """
    # Type check
    if not isinstance(data, dict):
        return False, "Payload must be a JSON object"

    # 1) Structural integrity
    for field in RequiredFields:
        if field not in data:
            return False, f"Missing required field: {field}"
        if data[field] is None:
            return False, f"Field '{field}' must not be null"

    # 2) Type and numeric checks for price/volume
    prices = {}
    for field in ("open", "high", "low", "close"):
        v = data[field]
        if not _is_number(v):
            return False, f"Field '{field}' must be a finite number"
        prices[field] = float(v)

    vol = data["volume"]
    if not _is_number(vol):
        return False, "Field 'volume' must be a finite number"
    volume = float(vol)

    # 3) Non-negative
    if any(x < 0 for x in prices.values()):
        return False, "Price fields must be non-negative"
    if volume < 0:
        return False, "Volume must be non-negative"

    # 4) OHLC coherence
    if not (prices["high"] >= prices["open"] and prices["high"] >= prices["close"]):
        return False, "High must be >= open and >= close"
    if not (prices["low"] <= prices["open"] and prices["low"] <= prices["close"]):
        return False, "Low must be <= open and <= close"
    if prices["high"] < prices["low"]:
        return False, "High must be >= low"

    # Structural sanity for other fields (lightweight)
    ticker = data.get("ticker_symbol")
    if not isinstance(ticker, str) or not ticker.strip():
        return False, "ticker_symbol must be a non-empty string"

    ts = data.get("timestamp_utc")
    if not isinstance(ts, str) or not ts.strip():
        return False, "timestamp_utc must be a non-empty string"

    return True, None

