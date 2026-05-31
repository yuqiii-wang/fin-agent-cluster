"""get_news — NodeTask to fetch raw news articles for a symbol/topic window.

Resolves a list of :class:`~backend.resources.news.models.NewsArticle` for the
requested window via one of two paths:

* injection      — ``json_input`` (list of article dicts) or ``text_content``
  handed down from a previous task; stored in ``fin_markets.input_raw`` and
  returned without any external call.
* external fetch  — request a news provider (FMP → DDGS fallback inside
  :class:`NewsClient`); raw articles are cached in ``input_raw``.

Execution layers
----------------
LangGraph layer (``_get_news_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Json")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    Dispatches to the injection or external-fetch path and caches the raw
    payload in ``fin_markets.input_raw``.  Empty external results raise.

Public exports
--------------
``get_news``       — ``NodeTask`` instance.
``GetNewsInput``   — Pydantic input model.
``GetNewsOutput``  — Pydantic output model.
``HANDLERS``       — dict slice for Celery handler registration.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_input_raw import InputRawSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    NEWS_TASK_ALL_PROVIDERS_EMPTY,
    NEWS_TASK_FETCH_ERROR,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask, get_task_cache_ttl
from backend.resources.news.client import NewsClient
from backend.resources.news.models import NewsArticle

logger = logging.getLogger(__name__)

_TASK_NAME = "get_news"
_NODE_NAME = "common_tasks/get_news"
_METHOD = "list_news"


def _date_bucket(dt: datetime | None) -> str:
    """Return a stable day-granularity bucket string for cache keying.

    Using day granularity keeps the cache key stable for repeated runs within
    the cache TTL even though the precise ``from_dt`` / ``to_dt`` shift slightly
    on every invocation.

    Args:
        dt: A datetime, or ``None``.

    Returns:
        ``YYYY-MM-DD`` string, or ``""`` when *dt* is ``None``.
    """
    return dt.strftime("%Y-%m-%d") if dt is not None else ""


def _make_cache_key(
    symbol: str | None,
    topics: list[str],
    from_dt: datetime | None,
    to_dt: datetime | None,
) -> str:
    """Compute a deterministic SHA-256 cache key for ``input_raw`` lookup.

    Args:
        symbol:  Ticker symbol or ``None``.
        topics:  Topic keywords.
        from_dt: Start of the date window.
        to_dt:   End of the date window.

    Returns:
        Hex-encoded 64-character SHA-256 digest.
    """
    payload = json.dumps(
        {
            "source": "news",
            "method": _METHOD,
            "symbol": (symbol or "").upper(),
            "topics": sorted(topics),
            "from": _date_bucket(from_dt),
            "to": _date_bucket(to_dt),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class GetNewsInput(BaseModel):
    """Input for the get_news task.

    Attributes:
        symbol:       Equity ticker, e.g. ``'AAPL'``.  ``None`` for topic-only.
        topics:       Topic keywords to narrow/augment the search.
        from_dt:      Start of the news date window (UTC).
        to_dt:        End of the news date window (UTC).
        news_limit:   Max number of articles to fetch.
        text_content: Free-form text to inject as a single article.
        json_input:   List of article dicts handed down from a previous task.
    """

    symbol: str | None = Field(default=None, description="Equity ticker, e.g. 'AAPL'.")
    topics: list[str] = Field(default_factory=list, description="Topic keywords to filter/augment search.")
    from_dt: datetime | None = Field(default=None, description="Start of date window (UTC).")
    to_dt: datetime | None = Field(default=None, description="End of date window (UTC).")
    news_limit: int = Field(default=20, ge=1, le=100, description="Max news articles to fetch.")
    text_content: str | None = Field(default=None, description="Free-form text to inject as one article.")
    json_input: list[dict] | None = Field(default=None, description="Injected NewsArticle dicts.")


class GetNewsOutput(BaseModel):
    """Output from the get_news task.

    Attributes:
        input_raw_id:  PK of the ``fin_markets.input_raw`` cache row inserted/reused.
        source:        Provider label actually used (``'fmp'``, ``'ddgs'``, ``'injected'``).
        news_articles: Raw articles resolved for the window.
        from_cache:    ``True`` when served from a fresh ``input_raw`` entry.
    """

    input_raw_id: int | None = Field(default=None, description="PK of the input_raw cache row.")
    source: str = Field(default="fmp", description="Provider label used.")
    news_articles: list[NewsArticle] = Field(default_factory=list, description="Resolved raw articles.")
    from_cache: bool = Field(default=False, description="True when served from cache.")


# ---------------------------------------------------------------------------
# Celery layer — business logic
# ---------------------------------------------------------------------------


async def _persist(
    thread_id: str | None,
    symbol: str | None,
    source: str,
    cache_key: str,
    ttl_seconds: int,
    input_payload: dict,
    articles: list[NewsArticle],
) -> int:
    """Insert raw articles into ``fin_markets.input_raw`` and return the new id.

    Args:
        thread_id:     LangGraph thread id for provenance (may be ``None``).
        symbol:        Ticker (uppercased) or ``None``.
        source:        Provider/source label.
        cache_key:     Deterministic cache key.
        ttl_seconds:   Per-row cache validity in seconds.
        input_payload: Request params (JSON-serialisable).
        articles:      Resolved articles to store.

    Returns:
        The inserted ``input_raw.id``.
    """
    output_payload = {"news_articles": [a.model_dump(mode="json") for a in articles]}
    async with raw_conn() as conn:
        cur = await conn.execute(
            InputRawSQL.INSERT_RETURNING,
            (
                thread_id,
                _NODE_NAME,
                (symbol or "").upper(),
                source,
                _METHOD,
                cache_key,
                ttl_seconds,
                json.dumps(input_payload),
                json.dumps(output_payload),
            ),
        )
        row = await cur.fetchone()
    return row["id"]


def _build_injected_articles(inp: GetNewsInput, symbol: str | None) -> list[NewsArticle]:
    """Build articles from injected ``json_input`` / ``text_content``.

    Args:
        inp:    Typed input with injection fields set.
        symbol: Ticker or ``None``.

    Returns:
        List of validated :class:`NewsArticle`.

    Raises:
        ValueError: When ``json_input`` items are not valid NewsArticle dicts.
    """
    if inp.json_input is not None:
        try:
            return [NewsArticle.model_validate(a) for a in inp.json_input]
        except Exception as exc:
            raise ValueError(
                f"[{NEWS_TASK_FETCH_ERROR}] invalid json_input articles: {exc}"
            ) from exc
    text = inp.text_content or ""
    url_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    return [
        NewsArticle(
            id=f"injected-{url_hash}",
            symbol=symbol,
            title=(text[:120] or "Injected content"),
            source="injected",
            content=text,
        )
    ]


async def _handler(payload: dict) -> dict:
    """Resolve raw news articles via injection or external fetch.

    Args:
        payload: Serialised :class:`GetNewsInput` dict.

    Returns:
        Serialised :class:`GetNewsOutput` dict.

    Raises:
        ValueError: When external providers return no articles, or injected
                    JSON is invalid.
    """
    inp = GetNewsInput.model_validate(payload)
    thread_id = payload.get("thread_id")
    symbol = inp.symbol.upper() if inp.symbol else None
    ttl_seconds = get_task_cache_ttl(_TASK_NAME)

    # Injection path — no external call.
    if inp.json_input is not None or inp.text_content:
        articles = _build_injected_articles(inp, symbol)
        cache_key = _make_cache_key(symbol, inp.topics, inp.from_dt, inp.to_dt)
        input_raw_id = await _persist(
            thread_id, symbol, "injected", cache_key, ttl_seconds,
            {"symbol": symbol, "topics": inp.topics, "injected": True},
            articles,
        )
        return GetNewsOutput(
            input_raw_id=input_raw_id, source="injected", news_articles=articles, from_cache=False,
        ).model_dump(mode="json")

    # External fetch path — cache check first.
    cache_key = _make_cache_key(symbol, inp.topics, inp.from_dt, inp.to_dt)
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(InputRawSQL.GET_CACHED, (cache_key,))
        cached_row = await cur.fetchone()

    if cached_row is not None:
        articles = [
            NewsArticle.model_validate(a)
            for a in cached_row["output"].get("news_articles", [])
        ]
        return GetNewsOutput(
            input_raw_id=cached_row["id"],
            source=cached_row["source"],
            news_articles=articles,
            from_cache=True,
        ).model_dump(mode="json")

    client = NewsClient()
    resp = await client.list_news(
        symbol=symbol,
        topics=inp.topics or None,
        from_dt=inp.from_dt,
        to_dt=inp.to_dt,
        limit=inp.news_limit,
    )

    if not resp.items:
        raise ValueError(
            f"[{NEWS_TASK_ALL_PROVIDERS_EMPTY}] No news for symbol={symbol} topics={inp.topics}"
        )

    source = client.provider
    articles = resp.items
    input_raw_id = await _persist(
        thread_id, symbol, source, cache_key, ttl_seconds,
        {"symbol": symbol, "topics": inp.topics, "from": _date_bucket(inp.from_dt), "to": _date_bucket(inp.to_dt)},
        articles,
    )
    return GetNewsOutput(
        input_raw_id=input_raw_id, source=source, news_articles=articles, from_cache=False,
    ).model_dump(mode="json")


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
        :class:`GetNewsOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")
    payload["thread_id"] = ctx.thread_id

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


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

get_news: NodeTask[GetNewsInput, GetNewsOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Resolve raw news articles for a symbol/topic/datetime window: fetch from a "
        "news provider (FMP → DDGS fallback) or inject json_input/text_content from a "
        "previous task. The raw payload is cached in fin_markets.input_raw."
    ),
    input_type=GetNewsInput,
    output_type=GetNewsOutput,
    task_fn=_get_news_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "get_news",
    "GetNewsInput",
    "GetNewsOutput",
    "HANDLERS",
]
