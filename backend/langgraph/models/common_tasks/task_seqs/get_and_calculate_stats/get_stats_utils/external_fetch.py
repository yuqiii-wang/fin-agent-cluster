"""external_fetch — provider and period fallback fetch handler for get_stats.

Tries each provider in the resolved chain; for each provider attempts the
requested period and falls back through :data:`PERIOD_FALLBACKS` before
moving to the next provider.  On success, persists the raw response to
``fin_markets.quant_raw`` and returns a serialised :class:`GetStatsOutput`.

Execution context: Celery layer (called from ``_handler``).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_indexes import derive_yf_exchange_from_ticker
from backend.db.postgres.queries.fin_markets_quant import QuantRawSQL
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_NO_DATA,
    STATS_TASK_PERIOD_FALLBACK,
    STATS_TASK_PROVIDER_FALLBACK,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.cache_key import (
    make_cache_key,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.provider_chain import (
    PERIOD_FALLBACKS,
    build_provider_chain,
)
from backend.resources.news.client import NewsClient
from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import StatsRecord

if TYPE_CHECKING:
    from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
        GetStatsInput,
    )

logger = logging.getLogger(__name__)


async def handle_external_fetch(inp: "GetStatsInput") -> dict:
    """Fetch OHLCV stats and news from external providers and cache in ``quant_raw``.

    Iterates the provider fallback chain resolved for *symbol*.  Within each
    provider, period fallbacks are attempted before moving to the next provider.
    The first successful response is persisted and returned.

    Args:
        inp: Typed :class:`GetStatsInput` (``json_input`` and ``text_content`` are
             both ``None`` when this handler is invoked).

    Returns:
        Serialised :class:`GetStatsOutput` dict.

    Raises:
        ValueError: When all providers return no data for the symbol/period.
    """
    from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
        GetStatsOutput,
    )

    symbol = inp.symbol.upper()
    method = "list_stats"
    providers = build_provider_chain(symbol)
    news_client = NewsClient()
    last_error: str | None = None

    for provider in providers:
        stats_client = StatsClient(symbol=symbol, force_provider=provider)
        try:
            source = stats_client.provider
            cache_key = make_cache_key(source, method, symbol, inp.period)
            periods_to_try = [inp.period] + PERIOD_FALLBACKS.get(inp.period, [])
            stats_record: StatsRecord | None = None
            actual_period = inp.period
            provider_fetch_failed = False

            for period_attempt in periods_to_try:
                try:
                    stats_resp = await stats_client.list_stats(symbol, period_attempt, limit=1)
                except Exception as exc:
                    last_error = f"provider={provider} period={period_attempt}: {exc}"
                    logger.error(
                        "[%s] symbol=%s provider=%s period=%s error=%s, trying next provider",
                        STATS_TASK_PROVIDER_FALLBACK, symbol, provider, period_attempt, exc,
                    )
                    provider_fetch_failed = True
                    break
                if stats_resp.items:
                    stats_record = stats_resp.items[0]
                    actual_period = period_attempt
                    break

            if provider_fetch_failed or stats_record is None:
                if not provider_fetch_failed:
                    last_error = (
                        f"provider={provider} returned no data for symbol={symbol} period={inp.period}"
                    )
                    logger.error(
                        "[%s] symbol=%s provider=%s returned no data, trying next provider",
                        STATS_TASK_PROVIDER_FALLBACK, symbol, provider,
                    )
                continue

            if actual_period != inp.period:
                logger.error(
                    "[%s] symbol=%s period=%s unavailable, fell back to period=%s",
                    STATS_TASK_PERIOD_FALLBACK, symbol, inp.period, actual_period,
                )

            news_resp = await news_client.list_news(symbol, limit=inp.news_limit)
            news_articles = news_resp.items

            output_payload: dict = {
                "stats_record": stats_record.model_dump(mode="json"),
                "news_articles": [a.model_dump(mode="json") for a in news_articles],
            }
            async with raw_conn() as conn:
                await conn.execute(
                    QuantRawSQL.INSERT,
                    (
                        None,
                        "common_tasks/get_stats",
                        source,
                        method,
                        symbol,
                        cache_key,
                        json.dumps({"symbol": symbol, "period": inp.period}),
                        json.dumps(output_payload),
                    ),
                )

            # Resolve yf_exchange for downstream indicator computation; result is
            # stored in quant_raw by the provider layer; no further action needed here.
            _ = stats_record.yf_exchange or derive_yf_exchange_from_ticker(symbol)

            return GetStatsOutput(
                stats_record=stats_record,
                news_articles=news_articles,
                from_cache=False,
            ).model_dump(mode="json")

        finally:
            await stats_client.aclose()

    raise ValueError(
        f"[{STATS_TASK_NO_DATA}] No stats data for symbol={symbol} period={inp.period} "
        f"from any provider. Last error: {last_error}"
    )


__all__ = ["handle_external_fetch"]
