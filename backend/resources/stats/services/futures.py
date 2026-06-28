"""Futures-contract stats service.

Handles futures tickers recognised by the ``=F`` suffix:
``CL=F`` (crude oil), ``ES=F`` (S&P 500 e-mini), ``YM=F`` (Dow),
``NQ=F`` (Nasdaq 100), ``GC=F`` (gold), ``SI=F`` (silver) ...

Futures are sourced from yfinance / FMP / mock using the same OHLCV
transport as stocks, but the yfinance path routes through
:mod:`backend.resources.stats.providers.yfinance.fetch_futures` so
the emitted record ID starts with ``yf-futures-``. That way
downstream consumers can distinguish futures-sourced bars from plain
equity bars without re-running symbol heuristics. FMP and mock still
use the stock fetcher (they don't emit a ``yf-futures-`` prefix) --
if you need distinct IDs from those backends, replace the branches
with dedicated ``fetch_futures`` equivalents.
"""

from __future__ import annotations

import logging

from _shared.httpx_client import AsyncClient
from backend.resources.stats.models import StatsListResponse, StatsRecord
from backend.resources.stats.providers.errors import (
    STATS_YFINANCE_EMPTY,
)
from backend.resources.stats.services.stock import list_stats as _stock_list
from backend.resources.stats.services.stock import get_stats as _stock_get

logger = logging.getLogger(__name__)


SUPPORTED_PROVIDERS = frozenset({"mock", "yfinance", "fmp"})


def supports_provider(provider: str) -> bool:
    """Return ``True`` when *provider* is supported for futures."""
    return provider in SUPPORTED_PROVIDERS


def _expand_periods(period: str | None) -> list[str]:
    return [period] if period else ["1d", "1w", "1mo", "3mo", "1y"]


async def list_stats(
    symbol: str,
    period: str | None,
    provider: str,
    http: AsyncClient | None,
    *,
    limit: int = 1,
) -> StatsListResponse:
    """Fetch OHLCV records for a futures ticker.

    Mirrors the robustness of :func:`stock.list_stats`.  For yfinance
    the caller's *period* is passed through verbatim (so period
    fallbacks in the upstream handler actually work).  When yfinance
    reports ``STATS_YFINANCE_EMPTY`` the period is skipped silently;
    any other error re-raises so the caller can record it and try the
    next provider.
    """
    if not supports_provider(provider):
        logger.warning("futures.list_stats: unsupported provider=%r", provider)
        return StatsListResponse(items=[], total=0)
    if provider == "yfinance":
        from backend.resources.stats.providers.yfinance import fetch_futures as _yf_futures

        items: list[StatsRecord] = []
        for p in _expand_periods(period):
            try:
                record: StatsRecord = await _yf_futures.fetch(symbol, p)
            except ValueError as exc:
                if STATS_YFINANCE_EMPTY in str(exc):
                    logger.warning(
                        "futures yfinance skip period=%s (empty): %s", p, exc,
                    )
                    continue
                raise
            if period is not None:
                try:
                    record = record.model_copy(update={"period": period})
                except Exception:
                    pass
            items.append(record)
        if limit < 1:
            items = []
        elif limit < len(items):
            items = items[:limit]
        return StatsListResponse(items=items, total=len(items))
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
