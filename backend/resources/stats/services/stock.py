"""Stock / equity stats service.

Dispatches OHLCV fetching for individual equities and A-shares to one
of the supported providers:

* ``"mock"``    -- in-process mock transport.
* ``"yfinance"``-- synchronous yfinance wrapped in an async executor.
* ``"fmp"``     -- REST API call via a pre-configured httpx client.
* ``"akshare"`` -- akshare library for Chinese A-shares.

Contract
--------
Callers invoke :func:`list_stats` and :func:`get_stats` without knowing
which provider is backing them.  The provider label is chosen upstream
in :class:`~backend.resources.stats.client.StatsClient` (using
ticker-suffix routing or ``Settings.STATS_PROVIDER``).
"""

from __future__ import annotations

import logging

from _shared.httpx_client import AsyncClient
from backend.resources.stats.models import StatsListResponse, StatsRecord
from backend.resources.stats.providers.errors import (
    STATS_AKSHARE_EMPTY,
    STATS_FMP_EMPTY,
    STATS_YFINANCE_EMPTY,
)

logger = logging.getLogger(__name__)


SUPPORTED_PROVIDERS = frozenset({"mock", "yfinance", "fmp", "akshare"})


def supports_provider(provider: str) -> bool:
    """Return ``True`` when *provider* is supported for stocks."""
    return provider in SUPPORTED_PROVIDERS


async def list_stats(
    symbol: str,
    period: str | None,
    provider: str,
    http: AsyncClient | None,
    *,
    limit: int = 1,
) -> StatsListResponse:
    """Fetch a single-stock OHLCV record from the selected provider.

    Args:
        symbol:   Ticker symbol, e.g. ``'AAPL'``, ``'600519.SS'``.
        period:   Aggregation period label (``'1d'``, ``'1mo'`` ...).
                  ``None`` expands to a default set of periods.
        provider: One of ``'mock'``, ``'yfinance'``, ``'fmp'``,
                  ``'akshare'``.
        http:     Pre-configured httpx client (required for ``'mock'``
                  and ``'fmp'``).
        limit:    Maximum number of records to return.

    Returns:
        :class:`~backend.resources.stats.models.StatsListResponse`.
    """
    if provider == "mock":
        return await _list_mock(symbol, period, http, limit=limit)
    if provider == "yfinance":
        return await _list_yfinance(symbol, period)
    if provider == "fmp":
        return await _list_fmp(symbol, period, http)
    if provider == "akshare":
        return await _list_akshare(symbol, period)
    logger.warning("stock.list_stats: unknown provider=%r returning empty", provider)
    return StatsListResponse(items=[], total=0)


async def get_stats(
    record_id: str,
    provider: str,
    http: AsyncClient | None,
) -> StatsRecord | None:
    """Fetch a single stock record by ID.

    Args:
        record_id: ``{provider}-{symbol}-{period}`` style ID.
        provider:  Provider label.
        http:      httpx client (``'mock'`` / ``'fmp'``).

    Returns:
        A :class:`~backend.resources.stats.models.StatsRecord` or
        ``None`` when the record cannot be resolved.
    """
    if provider == "mock":
        return await _get_mock(record_id, http)
    if provider == "yfinance":
        return await _get_yfinance(record_id)
    if provider == "fmp":
        return await _get_fmp(record_id, http)
    if provider == "akshare":
        return await _get_akshare(record_id)
    return None


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------


async def _list_mock(
    symbol: str | None,
    period: str | None,
    http: AsyncClient | None,
    *,
    limit: int,
) -> StatsListResponse:
    assert http is not None
    params: dict[str, str | int] = {"limit": limit}
    if symbol is not None:
        params["symbol"] = symbol
    if period is not None:
        params["period"] = period
    response = await http.get("/stats", params=params)
    if not response.is_success:
        raise ValueError(
            f"stats stock mock list failed: status={response.status_code} "
            f"body={response.text[:500]!r}"
        )
    items = [StatsRecord.model_validate(row) for row in response.json()]
    return StatsListResponse(items=items, total=len(items))


async def _get_mock(record_id: str, http: AsyncClient | None) -> StatsRecord | None:
    assert http is not None
    response = await http.get(f"/stats/{record_id}")
    if response.status_code == 404:
        return None
    if not response.is_success:
        raise ValueError(
            f"stats stock mock get failed: status={response.status_code} "
            f"body={response.text[:500]!r}"
        )
    return StatsRecord.model_validate(response.json())


def _expand_periods(period: str | None) -> list[str]:
    return [period] if period else ["1d", "1w", "1mo", "3mo", "1y"]


async def _list_yfinance(symbol: str, period: str | None) -> StatsListResponse:
    from backend.resources.stats.providers.yfinance.fetcher import fetch as yf_fetch

    items: list[StatsRecord] = []
    for p in _expand_periods(period):
        try:
            items.append(await yf_fetch(symbol, p))
        except ValueError as exc:
            if STATS_YFINANCE_EMPTY in str(exc):
                logger.warning("stock yfinance skip period=%s (empty): %s", p, exc)
            else:
                raise
    return StatsListResponse(items=items, total=len(items))


async def _get_yfinance(record_id: str) -> StatsRecord | None:
    from backend.resources.stats.providers.yfinance.fetcher import fetch as yf_fetch

    parts = record_id.split("-", 2)
    if len(parts) != 3 or parts[0] != "yf":
        logger.debug("stock.get_stats yfinance: unrecognised id %r", record_id)
        return None
    _, symbol, period = parts
    try:
        return await yf_fetch(symbol, period)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("stock.get_stats yfinance id=%r: %s", record_id, exc)
        return None


async def _list_fmp(
    symbol: str, period: str | None, http: AsyncClient | None
) -> StatsListResponse:
    from backend.resources.stats.providers.fmp.fetcher import fetch as fmp_fetch

    assert http is not None
    items: list[StatsRecord] = []
    for p in _expand_periods(period):
        try:
            items.append(await fmp_fetch(symbol, p, http))
        except ValueError as exc:
            if STATS_FMP_EMPTY in str(exc):
                logger.warning("stock fmp skip period=%s (empty): %s", p, exc)
            else:
                raise
    return StatsListResponse(items=items, total=len(items))


async def _get_fmp(record_id: str, http: AsyncClient | None) -> StatsRecord | None:
    from backend.resources.stats.providers.fmp.fetcher import fetch as fmp_fetch

    parts = record_id.split("-", 2)
    if len(parts) != 3 or parts[0] != "fmp":
        logger.debug("stock.get_stats fmp: unrecognised id %r", record_id)
        return None
    assert http is not None
    _, symbol, period = parts
    try:
        return await fmp_fetch(symbol, period, http)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("stock.get_stats fmp id=%r: %s", record_id, exc)
        return None


async def _list_akshare(symbol: str, period: str | None) -> StatsListResponse:
    from backend.resources.stats.providers.akshare.fetcher import fetch as ak_fetch

    items: list[StatsRecord] = []
    for p in _expand_periods(period):
        try:
            items.append(await ak_fetch(symbol, p))
        except ValueError as exc:
            if STATS_AKSHARE_EMPTY in str(exc):
                logger.warning("stock akshare skip period=%s (empty): %s", p, exc)
            else:
                raise
    return StatsListResponse(items=items, total=len(items))


async def _get_akshare(record_id: str) -> StatsRecord | None:
    from backend.resources.stats.providers.akshare.fetcher import fetch as ak_fetch

    parts = record_id.split("-", 2)
    if len(parts) != 3 or parts[0] != "ak":
        logger.debug("stock.get_stats akshare: unrecognised id %r", record_id)
        return None
    _, symbol, period = parts
    try:
        return await ak_fetch(symbol, period)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("stock.get_stats akshare id=%r: %s", record_id, exc)
        return None


__all__ = ["list_stats", "get_stats", "supports_provider"]
