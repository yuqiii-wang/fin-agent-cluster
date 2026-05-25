"""get_stats — common NodeTask to fetch market OHLCV stats and news from resource APIs.

Fetches OHLCV market data via :class:`~backend.resources.stats.client.StatsClient`
and recent news via :class:`~backend.resources.news.client.NewsClient` for a given
symbol and period.  The raw API response is cached in ``fin_markets.quant_raw`` with
a same-day TTL (midnight UTC); subsequent calls on the same calendar day are served
from the DB cache rather than making a new external request.

Execution layers
----------------
LangGraph layer (``_get_stats_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Stats")``, delegates to the Celery
    completion worker via ``delegate_completion``, and returns a ``TaskOutput``.
    On exception, calls ``complete_task(failed=True)`` to emit the failure SSE.

Celery layer (``_handler``):
    1. Computes a deterministic SHA-256 cache_key.
    2. Checks ``fin_markets.quant_raw`` for a fresh entry created on the same calendar day (UTC).
    3. On cache miss: calls StatsClient + NewsClient, inserts into ``quant_raw``.
    4. Returns serialised ``GetStatsOutput``.

Public exports
--------------
``get_stats``  — ``NodeTask`` instance used by node task runners.
``HANDLERS``   — dict slice for registration in ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.config import get_settings
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_indexes import derive_yf_exchange_from_ticker, upsert_stock_index_memberships
from backend.db.postgres.queries.fin_markets_quant import OhlcvStatsSQL, QuantRawSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats import PERIOD_TO_GRANULARITY
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_NO_DATA,
    STATS_TASK_PERIOD_FALLBACK,
    STATS_TASK_PROVIDER_FALLBACK,
)
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.resources.news.client import NewsClient
from backend.resources.news.models import NewsArticle
from backend.resources.stats.client import StatsClient
from backend.resources.stats.models import StatsRecord
from backend.resources.stats.routing import provider_for_symbol

logger = logging.getLogger(__name__)

_TASK_NAME = "get_stats"
_CACHE_TTL_HOURS = 4

# Ordered fallback chain: if the requested period returns no data, try the next shorter period.
_PERIOD_FALLBACKS: dict[str, list[str]] = {
    "2y": ["1y"],
    "1y": ["3mo"],
    "3mo": ["1mo"],
    "1mo": ["1w"],
    "1w": ["1d"],
}


_MIN_BARS_FOR_CORR = 2  # noqa: F401 (kept for calculate_corr parity)

# Ordered provider fallback chains: when the primary provider returns no data,
# the next provider in the list is tried before giving up.
_PROVIDER_FALLBACK_CHAINS: dict[str, list[str]] = {
    "fmp": ["fmp", "yfinance"],
    "yfinance": ["yfinance", "fmp"],
    "mock": ["mock"],
}


def _build_provider_chain(symbol: str) -> list[str]:
    """Return the ordered list of stats providers to try for *symbol*.

    The primary provider is resolved from ticker-suffix routing, then the
    remaining chain entries from :data:`_PROVIDER_FALLBACK_CHAINS` are
    appended.  ``fmp`` is excluded from the chain when ``FMP_API_KEY`` is
    not configured.

    Args:
        symbol: Normalised (uppercase) ticker symbol.

    Returns:
        Non-empty list of provider labels in priority order.
    """
    settings = get_settings()
    primary = provider_for_symbol(symbol) or (settings.STATS_PROVIDER or "mock").strip().lower()
    chain = _PROVIDER_FALLBACK_CHAINS.get(primary, [primary])
    if not settings.FMP_API_KEY:
        chain = [p for p in chain if p != "fmp"]
    return chain or ["mock"]


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class GetStatsInput(BaseModel):
    """Input for the get_stats task.

    Attributes:
        symbol:                   Equity ticker symbol, e.g. ``'AAPL'``.
        period:                   Aggregation period: ``'1d'``, ``'1w'``, ``'1mo'``, ``'3mo'``, ``'1y'``.
        news_limit:               Maximum number of news articles to fetch.
        bypass_threshold_minutes: If the last raw-data fetch was within this many minutes,
                                  signal downstream tasks to bypass recomputation and read
                                  directly from the DB.  Defaults to 60 minutes.
    """

    symbol: str = Field(description="Equity ticker symbol, e.g. 'AAPL'.")
    period: str = Field(description="Aggregation period: '1d', '1w', '1mo', '3mo', '1y', '2y'.")
    news_limit: int = Field(default=10, ge=1, le=50, description="Max news articles to fetch.")
    bypass_threshold_minutes: int = Field(
        default=60, ge=1, description="Minutes within which downstream stats recomputation is skipped."
    )


class GetStatsOutput(BaseModel):
    """Output from the get_stats task.

    Attributes:
        stats_record:      Fetched OHLCV stats record from the provider.
        news_articles:     Recent news articles for the symbol.
        from_cache:        ``True`` when the stats record was served from ``quant_raw`` cache.
        bypass_calculate:  ``True`` when the cached entry is fresh enough AND ``quant_stats``
                           already contains rows for the symbol/granularity, indicating that
                           downstream tasks (``calculate_stats``) can safely skip recomputation.
    """

    stats_record: StatsRecord
    news_articles: list[NewsArticle]
    from_cache: bool = Field(default=False)
    bypass_calculate: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache_key(source: str, method: str, symbol: str, period: str) -> str:
    """Compute a deterministic SHA-256 cache key for ``quant_raw`` lookup.

    Args:
        source: Provider name, e.g. ``'yfinance'``.
        method: API method name, e.g. ``'list_stats'``.
        symbol: Normalised (uppercase) ticker.
        period: Aggregation period string.

    Returns:
        Hex-encoded 64-character SHA-256 digest.
    """
    payload = json.dumps(
        {"source": source, "method": method, "symbol": symbol, "period": period},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Celery layer — business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Fetch OHLCV stats and news, writing the raw response to ``quant_raw``.

    Tries each provider in the fallback chain for the symbol.  For each
    provider, period fallbacks are attempted before moving to the next
    provider.  The first successful result is cached and returned.

    The pg cache check is handled upstream by ``run_task`` via ``pg_cache_fn``.
    This function is only reached on a cache miss.

    Args:
        payload: Serialised :class:`GetStatsInput` dict.

    Returns:
        Serialised :class:`GetStatsOutput` dict.

    Raises:
        ValueError: When all providers return no data for the symbol/period.
    """
    inp = GetStatsInput.model_validate(payload)
    symbol = inp.symbol.upper()
    method = "list_stats"
    bypass_cutoff = datetime.now(timezone.utc) - timedelta(minutes=inp.bypass_threshold_minutes)

    providers = _build_provider_chain(symbol)
    news_client = NewsClient()
    last_error: str | None = None

    for provider in providers:
        stats_client = StatsClient(symbol=symbol, force_provider=provider)
        try:
            source = stats_client.provider
            cache_key = _make_cache_key(source, method, symbol, inp.period)
            periods_to_try = [inp.period] + _PERIOD_FALLBACKS.get(inp.period, [])
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
                    last_error = f"provider={provider} returned no data for symbol={symbol} period={inp.period}"
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

            # --- persist in quant_raw (thread_id=None → cache is thread-agnostic) ---
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

            yf_exchange = stats_record.yf_exchange or derive_yf_exchange_from_ticker(symbol)
            await upsert_stock_index_memberships(symbol, yf_exchange)

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


# ---------------------------------------------------------------------------
# PG cache function
# ---------------------------------------------------------------------------


async def _get_stats_pg_cache(
    inp: GetStatsInput, ctx: NodeContext
) -> GetStatsOutput | None:
    """Check pg for a recent ``quant_raw`` record matching the same input parameters.

    Queries each provider's cache key in fallback order using a 4-hour TTL.
    On a hit, checks whether the cached entry is fresh enough to bypass
    downstream stats recomputation.

    Args:
        inp: Typed task input.
        ctx: Current node context (unused; present for signature compatibility).

    Returns:
        ``GetStatsOutput`` with ``from_cache=True`` on a cache hit, or ``None``.
    """
    symbol = inp.symbol.upper()
    method = "list_stats"
    ttl_cutoff = datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
    bypass_cutoff = datetime.now(timezone.utc) - timedelta(minutes=inp.bypass_threshold_minutes)
    providers = _build_provider_chain(symbol)

    for provider in providers:
        cache_key = _make_cache_key(provider, method, symbol, inp.period)
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


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_stats_task(
    task_input: TaskInput[GetStatsInput],
) -> TaskOutput[GetStatsOutput]:
    """LangGraph @task: delegates get_stats to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`GetStatsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`GetStatsOutput` from the Celery worker.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
    )
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload,
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise

    output = GetStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_stats = NodeTask(
    name=_TASK_NAME,
    description=(
        "Fetch OHLCV market statistics and recent news for an equity symbol from the "
        "configured stats provider (mock / yfinance / fmp).  Raw API responses are cached "
        "in fin_markets.quant_raw for the remainder of the same calendar day (UTC)."
    ),
    input_type=GetStatsInput,
    output_type=GetStatsOutput,
    task_fn=_get_stats_task,
    handler=_handler,
    pg_cache_fn=_get_stats_pg_cache,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = ["get_stats", "GetStatsInput", "GetStatsOutput", "HANDLERS"]
