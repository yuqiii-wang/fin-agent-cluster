"""yfinance stats fetcher — async wrapper around the synchronous yfinance library.

yfinance is a blocking library; all calls run in the default
``asyncio`` thread-pool executor via :func:`asyncio.get_event_loop().run_in_executor`
so the FastAPI event loop is never blocked.

Public API
----------
fetch(symbol, period)  — download OHLCV bars and return a StatsRecord.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

import yfinance as yf

from backend.resources.stats.errors import STATS_PROVIDER_ERROR, STATS_YFINANCE_EMPTY
from backend.resources.stats.models import StatsRecord
from backend.resources.stats.yfinance.transformer import period_args, transform

logger = logging.getLogger(__name__)


async def fetch(symbol: str, period: str) -> StatsRecord:
    """Download OHLCV data from Yahoo Finance and return a :class:`StatsRecord`.

    Runs the blocking ``yf.Ticker.history()`` call in a thread-pool executor
    so the asyncio event loop is not blocked.

    Args:
        symbol: Equity ticker, e.g. ``"AAPL"``.
        period: Aggregation period label — one of ``1d``, ``1w``, ``1mo``,
                ``3mo``, ``1y``.

    Returns:
        :class:`~backend.resources.stats.models.StatsRecord` with OHLCV series.

    Raises:
        ValueError: Propagated from :func:`~.transformer.transform` when
                    yfinance returns an empty DataFrame, carrying error code
                    :data:`~backend.resources.stats.errors.STATS_YFINANCE_EMPTY`.
    """
    yf_period, yf_interval = period_args(period)
    logger.info(
        "yfinance.fetch symbol=%s period=%s → yf_period=%s interval=%s",
        symbol, period, yf_period, yf_interval,
    )

    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(
            None,
            partial(_download, symbol, yf_period, yf_interval),
        )
    except Exception as exc:
        logger.warning(
            "yfinance.fetch error symbol=%s period=%s error=%s [%s]",
            symbol, period, exc, STATS_PROVIDER_ERROR,
        )
        raise ValueError(STATS_PROVIDER_ERROR) from exc

    if df.empty:
        logger.warning(
            "yfinance.fetch empty DataFrame symbol=%s period=%s [%s]",
            symbol, period, STATS_YFINANCE_EMPTY,
        )
        raise ValueError(STATS_YFINANCE_EMPTY)

    record = transform(symbol, period, df)
    logger.info("yfinance.fetch ok symbol=%s period=%s rows=%d", symbol, period, len(df))
    return record


# ---------------------------------------------------------------------------
# Sync helper — runs inside executor
# ---------------------------------------------------------------------------

def _download(
    symbol: str,
    yf_period: str,
    yf_interval: str,
) -> "pandas.DataFrame":  # type: ignore[name-defined]  # noqa: F821
    """Blocking yfinance download.  Called inside a thread-pool executor.

    Args:
        symbol:      Equity ticker.
        yf_period:   yfinance ``period`` arg, e.g. ``"5d"``.
        yf_interval: yfinance ``interval`` arg, e.g. ``"1h"``.

    Returns:
        ``pandas.DataFrame`` from ``yf.Ticker.history()``.
    """
    ticker = yf.Ticker(symbol)
    return ticker.history(period=yf_period, interval=yf_interval, auto_adjust=True)
