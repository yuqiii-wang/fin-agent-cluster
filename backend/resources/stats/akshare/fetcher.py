"""akshare stats fetcher — async wrapper around the synchronous akshare library.

akshare is a blocking library; all calls run in the default
``asyncio`` thread-pool executor via
:func:`asyncio.get_running_loop().run_in_executor` so the FastAPI event
loop is never blocked.

Supported symbols
-----------------
A-share tickers with ``.SS`` (Shanghai) or ``.SZ`` (Shenzhen) suffixes,
e.g. ``"600519.SS"``, ``"000858.SZ"``.

Public API
----------
fetch(symbol, period)  — download OHLCV bars and return a StatsRecord.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from functools import partial

import akshare as ak

from backend.resources.stats.errors import STATS_AKSHARE_EMPTY, STATS_PROVIDER_ERROR
from backend.resources.stats.models import StatsRecord
from backend.resources.stats.akshare.transformer import PERIOD_MAP, strip_suffix, transform

logger = logging.getLogger(__name__)


async def fetch(symbol: str, period: str) -> StatsRecord:
    """Download OHLCV data from akshare and return a :class:`StatsRecord`.

    Runs the blocking akshare calls in a thread-pool executor so the
    asyncio event loop is not blocked.

    Args:
        symbol: Equity ticker with yfinance-style suffix, e.g. ``"600519.SS"``.
        period: Aggregation period label — one of ``1d``, ``1w``, ``1mo``,
                ``3mo``, ``1y``, ``2y``.

    Returns:
        :class:`~backend.resources.stats.models.StatsRecord` with OHLCV series.

    Raises:
        ValueError: When akshare returns an empty DataFrame, carrying error
                    code :data:`~backend.resources.stats.errors.STATS_AKSHARE_EMPTY`.
        ValueError: On unexpected errors from the akshare library, carrying
                    error code :data:`~backend.resources.stats.errors.STATS_PROVIDER_ERROR`.
    """
    if period not in PERIOD_MAP:
        raise ValueError(f"Unsupported period '{period}' for akshare provider")

    ak_period, days_back = PERIOD_MAP[period]
    code = strip_suffix(symbol)
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    intraday = ak_period == "intraday"

    logger.debug(
        "akshare.fetch symbol=%s code=%s period=%s ak_period=%s start=%s end=%s",
        symbol, code, period, ak_period, start_date, end_date,
    )

    loop = asyncio.get_running_loop()
    try:
        if intraday:
            result = await loop.run_in_executor(
                None,
                partial(
                    _download_intraday,
                    code,
                    start_date.strftime("%Y-%m-%d %H:%M:%S"),
                    end_date.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
        else:
            result = await loop.run_in_executor(
                None,
                partial(
                    _download_daily,
                    code,
                    ak_period,
                    start_date.strftime("%Y%m%d"),
                    end_date.strftime("%Y%m%d"),
                ),
            )
    except Exception as exc:
        logger.error(
            "akshare.fetch error symbol=%s period=%s error=%s [%s]",
            symbol, period, exc, STATS_PROVIDER_ERROR,
        )
        raise ValueError(STATS_PROVIDER_ERROR) from exc

    if result.empty:
        logger.warning(
            "akshare.fetch empty DataFrame symbol=%s period=%s [%s]",
            symbol, period, STATS_AKSHARE_EMPTY,
        )
        raise ValueError(STATS_AKSHARE_EMPTY)

    record = transform(symbol, period, result, intraday=intraday)
    logger.debug("akshare.fetch ok symbol=%s period=%s rows=%d", symbol, period, len(result))
    return record


# ---------------------------------------------------------------------------
# Sync helpers — run inside thread-pool executor
# ---------------------------------------------------------------------------

def _download_daily(
    code: str,
    ak_period: str,
    start_date: str,
    end_date: str,
) -> "pandas.DataFrame":  # type: ignore[name-defined]  # noqa: F821
    """Blocking akshare daily/weekly download.

    Args:
        code:       6-digit A-share code, e.g. ``"600519"``.
        ak_period:  ``"daily"`` or ``"weekly"``.
        start_date: ``"YYYYMMDD"`` format start date.
        end_date:   ``"YYYYMMDD"`` format end date.

    Returns:
        ``pandas.DataFrame`` with A-share OHLCV columns.
    """
    return ak.stock_zh_a_hist(
        symbol=code,
        period=ak_period,
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )


def _download_intraday(
    code: str,
    start_date: str,
    end_date: str,
) -> "pandas.DataFrame":  # type: ignore[name-defined]  # noqa: F821
    """Blocking akshare 60-minute intraday download.

    Args:
        code:       6-digit A-share code, e.g. ``"600519"``.
        start_date: ``"YYYY-MM-DD HH:MM:SS"`` format start datetime.
        end_date:   ``"YYYY-MM-DD HH:MM:SS"`` format end datetime.

    Returns:
        ``pandas.DataFrame`` with intraday OHLCV columns.
    """
    return ak.stock_zh_a_hist_min_em(
        symbol=code,
        period="60",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )


__all__ = ["fetch"]
