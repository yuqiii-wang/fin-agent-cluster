"""Market-index stats service.

Index tickers (``^GSPC``, ``^HSI``, ``000300.SS`` ...) are fetched from
yfinance / FMP / mock using the same transport as stocks -- this service
just delegates to the stock provider helpers but keeps its own label
so callers can distinguish product types downstream.
"""

from __future__ import annotations

import logging

from _shared.httpx_client import AsyncClient
from backend.resources.stats.models import StatsListResponse, StatsRecord
from backend.resources.stats.services.stock import list_stats as _stock_list
from backend.resources.stats.services.stock import get_stats as _stock_get

logger = logging.getLogger(__name__)


SUPPORTED_PROVIDERS = frozenset({"mock", "yfinance", "fmp"})


def supports_provider(provider: str) -> bool:
    """Return ``True`` when *provider* is supported for indexes."""
    return provider in SUPPORTED_PROVIDERS


async def list_stats(
    symbol: str,
    period: str | None,
    provider: str,
    http: AsyncClient | None,
    *,
    limit: int = 1,
) -> StatsListResponse:
    """Fetch OHLCV records for an index ticker."""
    if not supports_provider(provider):
        logger.warning("index.list_stats: unsupported provider=%r", provider)
        return StatsListResponse(items=[], total=0)
    return await _stock_list(symbol, period, provider, http, limit=limit)


async def get_stats(
    record_id: str,
    provider: str,
    http: AsyncClient | None,
) -> StatsRecord | None:
    """Fetch a single index record by ID."""
    if not supports_provider(provider):
        return None
    return await _stock_get(record_id, provider, http)


__all__ = ["list_stats", "get_stats", "supports_provider"]
