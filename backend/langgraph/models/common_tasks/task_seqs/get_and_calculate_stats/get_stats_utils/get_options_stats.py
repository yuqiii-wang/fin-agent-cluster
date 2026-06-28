"""get_options_stats -- fetches an options-chain StatsRecord for a symbol.

This module contains the product-specific handler used by the main
``get_stats`` dispatcher for the ``'options'`` pipeline.  The key differences
from the OHLCV pipeline:

* ``StatsClient(force_product='options', maturity_horizon=...)`` is used.
* Period fallback does not apply to options chains.
* The cache key embeds the ``maturity_horizon`` short label (``next``, ``1w``,
  ``1mo``, ...) so each maturity window gets an independent cache slot.
* When every provider returns nothing or fails, the handler emits an empty
  ``GetStatsOutput`` instead of raising, so the downstream calculation path
  can still persist an empty aggregate row for observability.

Public exports
--------------
``get_options_stats_handler`` -- Celery-layer async handler function.
"""

from __future__ import annotations

import logging

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_input_raw import InputRawSQL
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_NO_DATA,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.common import (
    _METHOD,
    _TASK_NAME,
    _build_provider_chain,
    _horizon_label_and_seconds,
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

logger = logging.getLogger(__name__)


async def get_options_stats_handler(inp: GetStatsInput, symbol: str) -> dict:
    """Fetch an options-chain StatsRecord via StatsClient with provider fallback.

    Args:
        inp:    Typed input (no injection fields set). ``maturity_horizon``
                drives the cache key and the StatsClient call.
        symbol: Normalised ticker.

    Returns:
        Serialised :class:`GetStatsOutput` dict -- either the cached/fresh
        record, or an empty ``GetStatsOutput`` (with ``stats_record=None``)
        when no provider supplied options data for this symbol.
    """
    ttl_seconds = get_task_cache_ttl(_TASK_NAME)
    providers = _build_provider_chain(symbol)
    last_error: str | None = None

    # Translate the horizon to a human-friendly cache/tag label.
    options_label, _seconds = _horizon_label_and_seconds(inp.maturity_horizon)
    options_period = f"options-{options_label}"

    for provider in providers:
        cache_key = _make_cache_key(
            provider,
            _METHOD,
            symbol,
            options_period,
        )

        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(InputRawSQL.GET_CACHED, (cache_key,))
            cached_row = await cur.fetchone()

        if cached_row is not None:
            record = StatsRecord.model_validate(cached_row["output"]["stats_record"])
            return GetStatsOutput(
                stats_record=record,
                from_cache=True,
                pipeline=STATS_DATA_TYPE.OPTIONS.value,
            ).model_dump(mode="json")

        # Options: no period fallback (horizon already covers the window).
        period_try = inp.period
        try:
            client = StatsClient(
                symbol=symbol,
                force_provider=provider,
                force_product="options",
                maturity_horizon=inp.maturity_horizon,
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
            pipeline=STATS_DATA_TYPE.OPTIONS.value,
        ).model_dump(mode="json")

    # All providers exhausted with no usable data -- emit a best-effort empty
    # output instead of raising, so the call site can still surface the
    # missing-data reason without breaking the graph.
    logger.warning(
        "[%s] no options stats data for symbol=%r period=%r; last_error=%r",
        STATS_TASK_NO_DATA, symbol, inp.period, last_error,
    )
    return GetStatsOutput(
        stats_record=None,
        from_cache=False,
        pipeline=STATS_DATA_TYPE.OPTIONS.value,
        note=f"{STATS_TASK_NO_DATA}: provider chain returned no items",
    ).model_dump(mode="json")


__all__ = ["get_options_stats_handler"]
