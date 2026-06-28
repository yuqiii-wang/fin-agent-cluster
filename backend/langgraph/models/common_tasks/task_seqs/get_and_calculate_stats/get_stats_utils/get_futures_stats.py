"""get_futures_stats -- fetch OHLCV bars for futures contracts.

Futures tickers (``CL=F``, ``ES=F``, ``YM=F``, ``NQ=F``, ``GC=F``,
``SI=F``, ``BTC-USD``, ``ETH-USD``, ...) emit OHLCV bars identical in
shape to equities, but we stamp the resulting ``StatsRecord.id`` with
``yf-futures-`` so downstream routing can distinguish futures bars from
plain equity bars without re-running symbol heuristics.

Explicit routing
----------------
When the hosting node sets ``pipeline="futures"`` via :class:`GetStatsInput`,
this handler is invoked directly -- even for plain equity tickers (``AAPL``,
...). That is intentional: the caller wants the same data treated as a
futures-style bar series for the purpose of a multi-window analysis.

Public exports
--------------
``get_futures_stats_handler`` -- async Celery handler.
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


async def get_futures_stats_handler(inp: GetStatsInput, symbol: str) -> dict:
    """Fetch OHLCV bars for a futures-style ticker and persist a labelled record.

    Uses ``StatsClient(force_product="futures")`` so -- regardless of symbol
    shape -- the underlying provider call routes through the futures service
    (which on yfinance stamps the id with ``yf-futures-``).

    Mirrors the robustness of :func:`get_ohlcv_stats_handler`: provider
    fallback chain, period roll-down, per-provider cache keys so futures
    cache entries never collide with plain OHLCV cache entries for the
    same (symbol, period).

    Args:
        inp:    Typed :class:`GetStatsInput`. ``period`` is used verbatim.
        symbol: Normalised (uppercase) futures-style ticker.

    Returns:
        Serialised :class:`GetStatsOutput` dict.
    """

    ttl_seconds = get_task_cache_ttl(_TASK_NAME)
    providers = _build_provider_chain(symbol)
    last_error: str | None = None

    for provider in providers:
        cache_tag = f"futures:{provider}"
        cache_key = _make_cache_key(cache_tag, _METHOD, symbol, inp.period)

        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(InputRawSQL.GET_CACHED, (cache_key,))
            cached_row = await cur.fetchone()

        if cached_row is not None:
            record = StatsRecord.model_validate(cached_row["output"]["stats_record"])
            return GetStatsOutput(
                stats_record=record,
                from_cache=True,
                pipeline=STATS_DATA_TYPE.FUTURES.value,
            ).model_dump(mode="json")

        periods_to_try: list[str] = [inp.period]
        periods_to_try.extend(PERIOD_FALLBACKS.get(inp.period, []))

        for period_try in periods_to_try:
            try:
                client = StatsClient(
                    symbol=symbol,
                    force_provider=provider,
                    force_product="futures",
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
                pipeline=STATS_DATA_TYPE.FUTURES.value,
            ).model_dump(mode="json")

    raise ValueError(
        f"[{STATS_TASK_NO_DATA}] No futures stats data for symbol={symbol} "
        f"period={inp.period} from any provider. Last error: {last_error}"
    )


__all__ = ["get_futures_stats_handler"]
