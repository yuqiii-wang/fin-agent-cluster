"""Stats provider package.

Provides market statistics models, mock data, and the httpx client.

The ``content`` field is a time-series matrix:
  - x-axis: ordered ISO-8601 timestamps
  - y-axis: named series (close, volume, sma_20, rsi_14, …)

Sub-packages
------------
mock    — in-process mock transport + static records for offline / test use.
errors  — stats-specific error codes.

Exports
-------
StatsClient       — Async httpx client (mock provider by default).
StatsRecord       — Pydantic model for a single stats record.
StatsMatrix       — Pydantic model for the time-series matrix content.
StatsListResponse — Pydantic model for a paginated list.
"""

from __future__ import annotations

from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import StatsListResponse, StatsMatrix, StatsRecord

__all__ = ["StatsClient", "StatsRecord", "StatsMatrix", "StatsListResponse"]
