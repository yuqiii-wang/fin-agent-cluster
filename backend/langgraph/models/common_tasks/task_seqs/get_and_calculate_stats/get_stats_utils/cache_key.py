"""cache_key — deterministic SHA-256 key builder for quant_raw cache lookups."""

from __future__ import annotations

import hashlib
import json


def make_cache_key(source: str, method: str, symbol: str, period: str) -> str:
    """Compute a deterministic SHA-256 cache key for ``quant_raw`` lookup.

    Args:
        source: Provider name, e.g. ``'yfinance'``.
        method: API method name, e.g. ``'list_stats'``.
        symbol: Normalised (uppercase) ticker.
        period: Aggregation period string.

    Returns:
        Hex-encoded 64-character SHA-256 digest.
    """
    payload = json.dumps(
        {"source": source, "method": method, "symbol": symbol, "period": period},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["make_cache_key"]
