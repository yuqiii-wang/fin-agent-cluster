"""yfinance futures fetcher -- async wrapper for ``yf.Ticker.history``.

Takes any ticker the caller considers a "futures" contract
(``CL=F``, ``ES=F``, ``GC=F``, ``SI=F``, ``NG=F``, ``BTC-USD``,
``ETH-USD``, or even plain equity symbols like ``AAPL`` when the
caller wants the futures-style pipeline). The implementation uses
the same thread-pool executor pattern as
:mod:`backend.resources.stats.providers.yfinance.fetcher`, but returns
a record whose ID carries a ``yf-futures-`` prefix so downstream
callers can distinguish futures-sourced bars from plain equity bars
without consulting a separate DB column.

Public API
----------
``fetch(symbol, period)`` -- downloads OHLCV bars and returns a
:class:`~backend.resources.stats.models.StatsRecord` ready for the
quant_stats indicator pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial

import yfinance as yf

from backend.resources.stats.providers.errors import (
    STATS_PROVIDER_ERROR,
    STATS_YFINANCE_EMPTY,
)
from backend.resources.stats.models import StatsRecord
from backend.resources.stats.providers.yfinance.transformer import (
    period_args,
    transform,
)

logger = logging.getLogger(__name__)


# Reuse the shared ``period -> (yf_period, yf_interval)`` mapping so
# the futures path stays in sync with the main equity fetcher.
# Callers that want a distinct mapping can override this in the
# futures service module.
period_args = period_args


async def fetch(symbol: str, period: str) -> StatsRecord:
    """Download OHLCV bars for *symbol* from Yahoo Finance.

    Args:
        symbol: Ticker (equity or futures-style both accepted),
                e.g. ``"CL=F"``, ``"AAPL"``, ``"BTC-USD"``.
        period: Aggregation period label (``"1mo"``,
                ``"3mo"``, ``"1y"``, ``"2y"``).

    Returns:
        :class:`~backend.resources.stats.models.StatsRecord` whose
        ``id`` starts with ``"yf-futures-"`` (instead of the generic
        ``"yf-"``) so stats viewers / DB cache keys can tell futures
        records apart without a symbol heuristic.

    Raises:
        ValueError: if yfinance returns an empty DataFrame, or if the
        underlying network call fails.
    """

    yf_period, yf_interval = period_args(period)
    logger.info(
        "yfinance.fetch_futures symbol=%s period=%s -> yf_period=%s interval=%s",
        symbol, period, yf_period, yf_interval,
    )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(_download, symbol, yf_period, yf_interval),
        )
    except Exception as exc:
        logger.error(
            "yfinance.fetch_futures error symbol=%s period=%s error=%s [%s]",
            symbol, period, exc, STATS_PROVIDER_ERROR,
        )
        raise ValueError(STATS_PROVIDER_ERROR) from exc

    df = result["df"]
    if df.empty:
        logger.warning(
            "yfinance.fetch_futures empty DataFrame symbol=%s period=%s [%s]",
            symbol, period, STATS_YFINANCE_EMPTY,
        )
        raise ValueError(STATS_YFINANCE_EMPTY)

    record = transform(symbol, period, df)
    # Re-stamp the record id with a "yf-futures-" prefix so the
    # record is distinguishable from the generic equity record.
    # ``transform`` already emitted ``yf-{symbol}-{period}``.
    if record.id.startswith("yf-"):
        record.id = "yf-futures-" + record.id[len("yf-") :]
    logger.info(
        "yfinance.fetch_futures ok symbol=%s period=%s rows=%d id=%s",
        symbol, period, len(df), record.id,
    )
    return record


def _download(
    symbol: str,
    yf_period: str,
    yf_interval: str,
) -> dict:
    """Blocking yfinance download -- runs inside a thread-pool executor."""

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=yf_period, interval=yf_interval, auto_adjust=True)
    return {"df": df}


__all__ = ["fetch"]
