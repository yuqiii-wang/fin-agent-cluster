"""fetch_window: DB-first OHLCV window fetch for market_data_collector.

Input:  QuantClient, ticker, OhlcvWindow, thread_id, region
Output: tuple[list[OHLCVBar], str]  — (bars, source)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.graph.utils.ohlcv import get_ohlcv_coverage, fetch_ohlcv_from_db
from backend.resource_api.quant_api.client import QuantClient
from backend.resource_api.quant_api.constants import OhlcvWindow
from backend.resource_api.quant_api.models import OHLCVBar, QuantQuery, QuantResult
from backend.resource_api.quant_api.ohlcv_processor import resample_bars

logger = logging.getLogger(__name__)


async def fetch_window(
    qclient: QuantClient,
    ticker: str,
    window: OhlcvWindow,
    thread_id: Optional[str],
    region: Optional[str] = None,
) -> tuple[list[OHLCVBar], str]:
    """Check DB coverage for the OHLCV window and fetch only missing bars.

    For the 1h window, bars are fetched and stored at 1h granularity.
    Source selection is always ``'auto'`` — delegated to the region-aware
    :class:`~backend.resource_api.quant_api.client.QuantClient` chain.

    Args:
        qclient:   Shared QuantClient instance.
        ticker:    Ticker symbol.
        window:    OHLCV window configuration.
        thread_id: LangGraph thread id for cache tracing.
        region:    fin_markets.regions code for provider selection.

    Returns:
        Tuple of (bars, actual_source) where actual_source is the provider used.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window.window_days)

    latest = await get_ohlcv_coverage(ticker, window.granularity, window_start)

    fresh_cutoff = now - timedelta(hours=window.fresh_hours)
    if latest is not None and latest >= fresh_cutoff:
        logger.info("[quant tasks] %s/%s up-to-date (latest=%s); loading from DB", ticker, window.granularity, latest)
        db_bars = await fetch_ohlcv_from_db(ticker, window.granularity, window_start)
        if db_bars:
            return db_bars, "db"
        # DB reported fresh coverage but returned no bars — fall through to resource API
        logger.warning(
            "[quant tasks] %s/%s DB fresh but empty; falling back to resource API",
            ticker, window.granularity,
        )
        latest = None  # force full-period fetch below

    params: dict
    if latest is not None:
        params = {"interval": window.fetch_interval, "start": latest.isoformat()}
        logger.info("[quant tasks] incremental fetch %s/%s from %s", ticker, window.granularity, latest)
    else:
        params = {"interval": window.fetch_interval, "period": window.period}
        logger.info("[quant tasks] full fetch %s/%s period=%s", ticker, window.granularity, window.period)

    result: QuantResult = await qclient.fetch(
        QuantQuery(
            symbol=ticker,
            method="periodic_ohlcv",
            params=params,
            thread_id=thread_id,
            node_name="market_data_collector",
        ),
        source="auto",
        region=region,
    )
    bars = result.bars or []

    if bars and window.fetch_interval != window.interval:
        bars = resample_bars(bars, window.interval)

    return bars, result.source
