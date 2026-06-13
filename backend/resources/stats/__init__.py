"""Stats provider package.

Provides market statistics models, mock data, and the httpx client.

The ``content`` field is a time-series matrix:
  - x-axis: ordered ISO-8601 timestamps
  - y-axis: named series (close, volume, sma_20, rsi_14, ...)

Sub-packages
------------
mock    -- in-process mock transport + static records for offline / test use.
errors  -- stats-specific error codes.
routing -- ticker-suffix-to-provider mapping (US/HK -> fmp, CN -> yfinance).

Exports
-------
StatsClient   -- Async httpx client; routes to provider by ticker suffix.
StatsRecord   -- Pydantic model for a single stats record.
OhlcvStatsMatrix -- Pydantic model for the OHLCV time-series matrix content.
StatsListResponse -- Pydantic model for a paginated list.
provider_for_symbol -- Look up the designated provider for a ticker symbol.
"""

from __future__ import annotations

from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import OhlcvStatsMatrix, StatsListResponse, StatsRecord
from backend.resources.stats.routing import provider_for_symbol

__all__ = ["StatsClient", "StatsRecord", "OhlcvStatsMatrix", "StatsListResponse", "provider_for_symbol"]
