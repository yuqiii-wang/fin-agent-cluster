"""pg_cache — PG cache lookup for get_stats using fin_markets.quant_raw.

Checks whether a recent ``quant_raw`` entry exists for the requested symbol/period
and returns a cached :class:`~get_stats.GetStatsOutput` on a hit, skipping the
external API call entirely.

Execution context: LangGraph layer (called before delegating to Celery).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_quant import OhlcvStatsSQL, QuantRawSQL
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils import (
    PERIOD_TO_GRANULARITY,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.cache_key import (
    make_cache_key,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.provider_chain import (
    build_provider_chain,
)
from backend.resources.news.models import NewsArticle
from backend.resources.stats.models import StatsRecord

if TYPE_CHECKING:
    from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
        GetStatsInput,
        GetStatsOutput,
    )
    from backend.langgraph.models.models import NodeContext

logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS: int = 4


async def get_stats_pg_cache(
    inp: "GetStatsInput", ctx: "NodeContext"
) -> "GetStatsOutput | None":
    """Check ``quant_raw`` for a recent cached entry matching the input parameters.

    Queries each provider's cache key in fallback order using a 4-hour TTL.
    On a hit, checks whether the cached entry is fresh enough to bypass
    downstream stats recomputation.

    Skips the cache entirely for injection paths (``text_content`` or
    ``json_input`` provided) since those are always treated as fresh writes.

    Args:
        inp: Typed task input.
        ctx: Current node context (unused; present for signature compatibility).

    Returns:
        :class:`GetStatsOutput` with ``from_cache=True`` on a cache hit, or ``None``.
    """
    # Injection paths are always fresh — skip cache.
    if inp.text_content or inp.json_input is not None:
        return None

    from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
        GetStatsOutput,
    )

    symbol = inp.symbol.upper()
    method = "list_stats"
    ttl_cutoff = datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
    bypass_cutoff = datetime.now(timezone.utc) - timedelta(minutes=inp.bypass_threshold_minutes)
    providers = build_provider_chain(symbol)

    for provider in providers:
        cache_key = make_cache_key(provider, method, symbol, inp.period)
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(QuantRawSQL.GET_CACHED, (cache_key, ttl_cutoff))
            row = await cur.fetchone()
        if row is None:
            continue
        cached: dict = row["output"]
        stats_record = StatsRecord.model_validate(cached["stats_record"])
        news_articles = [NewsArticle.model_validate(a) for a in cached.get("news_articles", [])]
        created_at: datetime = row["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        bypass_calculate = False
        if created_at >= bypass_cutoff:
            granularity = PERIOD_TO_GRANULARITY.get(inp.period)
            if granularity:
                async with raw_conn(readonly=True) as conn:
                    cur = await conn.execute(
                        OhlcvStatsSQL.COUNT_BY_SYMBOL_GRANULARITY, (symbol, granularity)
                    )
                    count_row = await cur.fetchone()
                bypass_calculate = count_row is not None and count_row["row_count"] > 0
        return GetStatsOutput(
            stats_record=stats_record,
            news_articles=news_articles,
            from_cache=True,
            bypass_calculate=bypass_calculate,
        )
    return None


__all__ = ["get_stats_pg_cache"]
