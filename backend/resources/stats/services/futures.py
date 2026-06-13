"""Futures-contract stats service.

Handles futures tickers recognised by the ``=F`` suffix:
``CL=F`` (crude oil), ``ES=F`` (S&P 500 e-mini), ``YM=F`` (Dow),
``NQ=F`` (Nasdaq 100), ``GC=F`` (gold), ``SI=F`` (silver) ...

Futures are sourced from yfinance / FMP / mock using the same OHLCV
transport as stocks; this module keeps its own provider set and
provides a hook for future futures-specific endpoints (e.g. chain
lookups via FMP).
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
    """Return ``True`` when *provider* is supported for futures."""
    return provider in SUPPORTED_PROVIDERS


async def list_stats(
    symbol: str,
    period: str | None,
    provider: str,
    http: AsyncClient | None,
    *,
    limit: int = 1,
) -> StatsListResponse:
    """Fetch OHLCV records for a futures ticker."""
    if not supports_provider(provider):
        logger.warning("futures.list_stats: unsupported provider=%r", provider)
        return StatsListResponse(items=[], total=0)
    return await _stock_list(symbol, period, provider, http, limit=limit)


async def get_stats(
    record_id: str,
    provider: str,
    http: AsyncClient | None,
) -> StatsRecord | None:
    """Fetch a single futures record by ID."""
    if not supports_provider(provider):
        return None
    return await _stock_get(record_id, provider, http)


__all__ = ["list_stats", "get_stats", "supports_provider"]
