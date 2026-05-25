"""get_news — NodeTask to fetch news articles and web-search info, cache to news_raw.

Fetches news via :class:`~backend.resources.news.client.NewsClient` (FMP primary,
DDGS fallback) and web-search snippets via DDGS text search
for a given symbol, topic list, and datetime window.  The combined raw output is
cached in ``fin_markets.news_raw`` with a 4-hour TTL; subsequent calls within the
TTL return the cached result.

Execution layers
----------------
LangGraph layer (``_get_news_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="News")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    1. Computes a deterministic SHA-256 cache_key.
    2. Checks ``news_raw`` for a fresh entry within the 4-hour TTL.
    3. On cache miss: fetches from NewsClient (news + web-search), inserts to ``news_raw``.
    4. Returns serialised ``GetNewsOutput``.

Public exports
--------------
``get_news``   — ``NodeTask`` instance.
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
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_news import NewsRawSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    NEWS_TASK_FETCH_ERROR,
)
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.resources.news.client import NewsClient
from backend.resources.news.models import NewsArticle

logger = logging.getLogger(__name__)

_TASK_NAME = "get_news"
_CACHE_TTL_HOURS = 4
_NODE_NAME = "common_tasks/get_news"
_METHOD = "list_news"


def _floor_to_4h_block(dt: datetime) -> datetime:
    """Truncate a datetime to the nearest 4-hour UTC block (0, 4, 8, 12, 16, 20).

    Args:
        dt: Datetime to floor (may be timezone-aware).

    Returns:
        Datetime with hour floored to the 4-hour boundary, minutes/seconds/microseconds zeroed.
    """
    block_hour = (dt.hour // 4) * 4
    return dt.replace(hour=block_hour, minute=0, second=0, microsecond=0)


def _make_cache_key(
    symbol: str | None,
    topics: list[str] | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
) -> str:
    """Build a deterministic SHA-256 cache key from the fetch parameters.

    ``from_dt`` and ``to_dt`` are floored to 4-hour UTC blocks so that
    requests made within the same 4-hour window produce the same cache key
    regardless of sub-block timestamp differences.

    Args:
        symbol:  Equity ticker or None.
        topics:  Topic filter list or None.
        from_dt: Start of the date window or None.
        to_dt:   End of the date window or None.

    Returns:
        Hex SHA-256 string.
    """
    payload = json.dumps(
        {
            "symbol": symbol,
            "topics": sorted(topics) if topics else [],
            "from_dt": _floor_to_4h_block(from_dt).isoformat() if from_dt else None,
            "to_dt": _floor_to_4h_block(to_dt).isoformat() if to_dt else None,
        },
        sort_keys=True,
    )
    return hashlib.sha256(f"get_news:{payload}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class GetNewsInput(BaseModel):
    """Input for the get_news task.

    Attributes:
        symbol:      Primary equity ticker, e.g. ``'AAPL'``.  ``None`` for
                     topic-only news.
        topics:      Topic keyword list to narrow the search, e.g.
                     ``["earnings", "guidance"]``.
        from_dt:     Earliest article datetime (UTC).  ``None`` to let the
                     provider default.
        to_dt:       Latest article datetime (UTC).  ``None`` to let the
                     provider default.
        news_limit:  Maximum number of news articles to fetch from NewsClient.
        bypass_threshold_minutes: Cache bypass threshold in minutes.
    """

    symbol: str | None = Field(default=None, description="Equity ticker, e.g. 'AAPL'.")
    topics: list[str] = Field(default_factory=list, description="Topic keywords to filter/augment search.")
    from_dt: datetime | None = Field(default=None, description="Start of date window (UTC).")
    to_dt: datetime | None = Field(default=None, description="End of date window (UTC).")
    news_limit: int = Field(default=20, ge=1, le=100, description="Max news articles to fetch.")
    bypass_threshold_minutes: int = Field(
        default=240, ge=1, description="Minutes within which cached result is reused."
    )
    thread_id: str | None = Field(default=None, description="Originating LangGraph thread UUID for provenance.")


class GetNewsOutput(BaseModel):
    """Output from the get_news task.

    Attributes:
        news_raw_id:    DB row ID of the inserted ``news_raw`` record.
                        ``None`` when served from cache.
        news_articles:  Fetched news articles (FMP provider) plus DDGS web-search
                        results converted to :class:`NewsArticle`.
        from_cache:     ``True`` when served from the ``news_raw`` cache.
    """

    news_raw_id: int | None = Field(default=None)
    source: str = Field(default="fmp", description="Primary news provider used — 'fmp' or 'ddgs'.")
    news_articles: list[NewsArticle]
    from_cache: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Celery handler
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Celery-layer business logic for get_news.

    The pg cache check is handled upstream by ``run_task`` via ``pg_cache_fn``.
    This function is only reached on a cache miss.

    Args:
        payload: Serialised :class:`GetNewsInput` fields.

    Returns:
        Serialised :class:`GetNewsOutput` dict.
    """
    inp = GetNewsInput.model_validate(payload)

    symbol = inp.symbol.upper() if inp.symbol else None
    topics = inp.topics or None
    cache_key = _make_cache_key(symbol, inp.topics or None, inp.from_dt, inp.to_dt)

    # --- fetch from providers ---
    news_client = NewsClient()

    try:
        news_resp = await news_client.list_news(
            symbol=symbol,
            topics=topics,
            from_dt=inp.from_dt,
            to_dt=inp.to_dt,
            limit=inp.news_limit,
        )
        news_articles = news_resp.items
    except Exception as exc:
        logger.error("[%s] get_news news fetch failed symbol=%s error=%s", NEWS_TASK_FETCH_ERROR, symbol, exc)
        news_articles = []

    # --- persist to news_raw ---
    output_payload = {
        "news_articles": [a.model_dump(mode="json") for a in news_articles],
    }
    input_payload = {
        "symbol": symbol,
        "topics": inp.topics,
        "from_dt": inp.from_dt.isoformat() if inp.from_dt else None,
        "to_dt": inp.to_dt.isoformat() if inp.to_dt else None,
    }
    async with raw_conn() as conn:
        cur = await conn.execute(
            NewsRawSQL.INSERT_RETURNING,
            (
                inp.thread_id,
                _NODE_NAME,
                news_client.provider,
                _METHOD,
                cache_key,
                json.dumps(input_payload),
                json.dumps(output_payload),
            ),
        )
        row = await cur.fetchone()
        news_raw_id: int | None = row["id"] if row else None

    return GetNewsOutput(
        news_raw_id=news_raw_id,
        source=news_client.provider,
        news_articles=news_articles,
        from_cache=False,
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# PG cache function
# ---------------------------------------------------------------------------


async def _get_news_pg_cache(
    inp: GetNewsInput, ctx: NodeContext
) -> GetNewsOutput | None:
    """Check pg for a recent ``news_raw`` record matching the same input parameters.

    Queries ``NewsRawSQL.GET_CACHED`` using a 4-hour TTL.

    Args:
        inp: Typed task input.
        ctx: Current node context (unused; present for signature compatibility).

    Returns:
        ``GetNewsOutput`` with ``from_cache=True`` on a cache hit, or ``None``.
    """
    symbol = inp.symbol.upper() if inp.symbol else None
    cache_key = _make_cache_key(symbol, inp.topics or None, inp.from_dt, inp.to_dt)
    ttl_cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(NewsRawSQL.GET_CACHED, (cache_key, ttl_cutoff))
        row = await cur.fetchone()
    if row is None:
        return None
    cached: dict = row["output"]
    news_articles = [NewsArticle.model_validate(a) for a in cached.get("news_articles", [])]
    return GetNewsOutput(
        news_raw_id=row["id"],
        source=row["source"],
        news_articles=news_articles,
        from_cache=True,
    )


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _get_news_task(
    task_input: TaskInput[GetNewsInput],
) -> TaskOutput[GetNewsOutput]:
    """LangGraph @task: delegates get_news to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`GetNewsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`GetNewsOutput` from the Celery worker.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Json",
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
    output = GetNewsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


get_news: NodeTask[GetNewsInput, GetNewsOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Fetch news articles (FMP primary, DDGS fallback) and web-search snippets (DDGS) for a symbol "
        "and optional topic/datetime filter.  Caches raw output in fin_markets.news_raw."
    ),
    input_type=GetNewsInput,
    output_type=GetNewsOutput,
    task_fn=_get_news_task,
    handler=_handler,
    pg_cache_fn=_get_news_pg_cache,
)

HANDLERS: dict[str, object] = {_TASK_NAME: _handler}

__all__ = ["GetNewsInput", "GetNewsOutput", "get_news", "HANDLERS"]
