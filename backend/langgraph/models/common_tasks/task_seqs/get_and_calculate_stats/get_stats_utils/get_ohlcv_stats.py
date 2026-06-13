"""get_ohlcv_stats -- fetches an OHLCV bars StatsRecord for a symbol/period.

This module contains the product-specific handler used by the main
``get_stats`` dispatcher for the default ``'ohlcv'`` pipeline (equities,
indexes, crypto, commodities, precious metals, futures bars, etc.).

Implementation
--------------
* ``StatsClient(force_product=None)`` is used for OHLCV fetches.
* Period roll-down via ``PERIOD_FALLBACKS`` applies only to this pipeline
  (options don't use it).
* The resulting record is persisted to ``fin_markets.input_raw`` and returned
  with ``pipeline='ohlcv'``.

Public exports
--------------
``get_ohlcv_stats_handler`` -- Celery-layer async handler function.
"""

from __future__ import annotations

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_input_raw import InputRawSQL
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_NO_DATA,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.common import (
    PERIOD_FALLBACKS,
    _METHOD,
    _TASK_NAME,
    _build_provider_chain,
    _log_period_fallback,
    _log_provider_error,
    _make_cache_key,
    _persist,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.models import (
    GetStatsInput,
    GetStatsOutput,
)
from backend.langgraph.models.task import get_task_cache_ttl
from backend.quant.stats import STATS_DATA_TYPE
from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import StatsRecord


async def get_ohlcv_stats_handler(inp: GetStatsInput, symbol: str) -> dict:
    """Fetch an OHLCV StatsRecord via StatsClient with provider/period fallback.

    Args:
        inp:    Typed input (no injection fields set; caller handles those).
        symbol: Normalised ticker.

    Returns:
        Serialised :class:`GetStatsOutput` dict.

    Raises:
        ValueError: When no provider/period combination returns data.
    """
    ttl_seconds = get_task_cache_ttl(_TASK_NAME)
    providers = _build_provider_chain(symbol)
    last_error: str | None = None

    for provider in providers:
        cache_key = _make_cache_key(provider, _METHOD, symbol, inp.period)

        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(InputRawSQL.GET_CACHED, (cache_key,))
            cached_row = await cur.fetchone()

        if cached_row is not None:
            record = StatsRecord.model_validate(cached_row["output"]["stats_record"])
            return GetStatsOutput(
                stats_record=record,
                from_cache=True,
                pipeline=STATS_DATA_TYPE.OHLCV.value,
            ).model_dump(mode="json")

        periods_to_try: list[str] = [inp.period]
        periods_to_try.extend(PERIOD_FALLBACKS.get(inp.period, []))

        for period_try in periods_to_try:
            try:
                client = StatsClient(
                    symbol=symbol,
                    force_provider=provider,
                    force_product=None,
                    maturity_horizon=None,
                )
                try:
                    resp = await client.list_stats(symbol, period_try, limit=1)
                finally:
                    await client.aclose()
            except Exception as exc:
                last_error = str(exc)
                _log_provider_error(symbol, provider, period_try, exc)
                continue

            if not resp.items:
                if period_try != inp.period:
                    _log_period_fallback(symbol, provider, period_try)
                continue

            record = resp.items[0]
            await _persist(
                inp.thread_id, symbol, provider, _METHOD, cache_key, ttl_seconds,
                {"symbol": symbol, "period": inp.period},
                {"stats_record": record.model_dump(mode="json")},
            )
            return GetStatsOutput(
                stats_record=record,
                from_cache=False,
                pipeline=STATS_DATA_TYPE.OHLCV.value,
            ).model_dump(mode="json")

    raise ValueError(
        f"[{STATS_TASK_NO_DATA}] No OHLCV stats data for symbol={symbol} "
        f"period={inp.period} from any provider. Last error: {last_error}"
    )


__all__ = ["get_ohlcv_stats_handler"]
