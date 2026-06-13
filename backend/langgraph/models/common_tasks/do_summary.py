"""do_summary -- NodeTask: streaming LLM-classify and summarise news articles.

Batches all qualifying :class:`~backend.resources.news.models.NewsArticle` items
from the ``get_news`` output into a single streaming LLM prompt and classifies
each to produce:

* ``summary``          -- content verbatim (<=500 chars) or 2-3 sentence compressed summary
* ``sentiment_level``  -- one of the 9 sentiment codes
* ``topic``            -- one topic code from ``news_topics``
* ``tags``             -- free-form tag list

Failure behaviour
-----------------
Streaming failure (Celery infra down) propagates to seq.py for warning-level handling.
Per-article parse failure -> warning logged, article skipped (no entry in output summaries).
The task is a soft-failure task; seq.py continues without summaries on failure.

Execution layers
----------------
LangGraph layer (``_do_summary_task`` decorated with ``@task``):
    Cache-hit fast path: if summaries already exist in ``news_stats``, returns
    a ToolCall task and skips the LLM.
    No-content fast path: if no qualifying articles exist, returns empty ToolCall.
    Normal path: creates a Streaming task, delegates to the Celery stream worker,
    parses the JSON answer, and completes the task.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_do_summary_prompt``.
    A single batched prompt classifies all articles; tokens stream to the UI.

Public exports
--------------
``do_summary``             -- ``NodeTask`` instance.
``SummaryRecord``          -- Pydantic model for per-article LLM classification output.
``STREAM_PROMPT_BUILDERS`` -- dict slice for registration in ``stream_task._get_stream_prompt_builders``.
``HANDLERS``               -- empty dict (streaming task; no completion handler).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_news import NewsStatsSQL, NewsTopicsSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import NEWS_TASK_DIGEST_ERROR
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask
from backend.resources.news.models import NewsArticle

logger = logging.getLogger(__name__)

_TASK_NAME = "do_summary"
_MIN_CONTENT_LEN = 50   # articles shorter than this are skipped entirely; DDGS snippets are 100-200 chars

# ---------------------------------------------------------------------------
# Valid reference values for structured output validation
# ---------------------------------------------------------------------------

_SENTIMENT_LEVELS = frozenset({
    "strongly_bullish", "bullish", "mildly_bullish", "slightly_bullish",
    "neutral",
    "slightly_bearish", "mildly_bearish", "bearish", "strongly_bearish",
})

# ---------------------------------------------------------------------------
# News topics -- loaded from fin_markets.news_topics on first use
# ---------------------------------------------------------------------------

_topics_cache: dict[str, str | None] | None = None


async def _load_news_topics() -> dict[str, str | None]:
    """Load topic codes and descriptions from ``fin_markets.news_topics`` (cached after first load).

    Returns:
        Dict mapping topic code to its description (or ``None`` if absent).
    """
    global _topics_cache
    if _topics_cache is not None:
        return _topics_cache
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(NewsTopicsSQL.GET_ALL)
        rows = await cur.fetchall()
    _topics_cache = {row["code"]: row["description"] for row in rows}
    return _topics_cache


def _get_topics_sync() -> dict[str, str | None]:
    """Sync wrapper for :func:`_load_news_topics`; safe to call from Celery workers.

    Returns:
        Dict mapping topic code to its description.
    """
    if _topics_cache is not None:
        return _topics_cache
    return asyncio.run(_load_news_topics())


def _build_batch_system_prompt(topics: dict[str, str | None]) -> str:
    """Build the batch system prompt with the topic list loaded from DB.

    Args:
        topics: Dict mapping topic code to description from ``fin_markets.news_topics``.

    Returns:
        System prompt string for the batched LLM classification call.
    """
    topics_lines = "\n".join(
        f"  - {code}" + (f": {desc}" if desc else "")
        for code, desc in sorted(topics.items())
    ) + "\n  - null"
    codes_str = " | ".join(sorted(topics.keys())) + " | null"
    return (
        "You are a financial news analyst. Given a list of articles, classify each one and respond\n"
        "ONLY with valid JSON matching the schema below. Do not think out loud -- output only the JSON object.\n"
        "\n"
        "Rules:\n"
        "- summary: if the article body is 500 characters or fewer, copy it verbatim; otherwise write\n"
        "  a 2-3 sentence compressed neutral summary.\n"
        "- topic: pick the single most relevant topic from the allowed list below.\n"
        "- tags: a few concise free-form descriptors (e.g. ticker names, event types, key themes).\n"
        "\n"
        f"Allowed topics:\n{topics_lines}\n"
        "\n"
        "Schema:\n"
        "{\n"
        '  "summaries": {\n'
        '    "<url_hash>": {\n'
        '      "summary":         "<verbatim body if <=500 chars, else 2-3 sentence compressed summary>",\n'
        '      "sentiment_level": "<one of: strongly_bullish | bullish | mildly_bullish | slightly_bullish | neutral | slightly_bearish | mildly_bearish | bearish | strongly_bearish>",\n'
        f'      "topic":           "<one of: {codes_str}>",\n'
        '      "tags":            ["<tag1>", "<tag2>"]\n'
        "    }\n"
        "  }\n"
        "}"
    )


def _url_hash(url: str | None, title: str) -> str:
    """Compute sha256 of URL, falling back to title when url is absent."""
    key = url or title
    return hashlib.sha256(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Prompt template (module-level global)
# The system message content is built dynamically from DB topics at call time
# and passed in via format_messages; only the structure is fixed here.
# ---------------------------------------------------------------------------

_DO_SUMMARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system_content}"),
    ("human", "Classify the following articles:\n\n{articles_text}"),
])


def _build_do_summary_prompt(payload: dict) -> list[BaseMessage]:
    """Build the batched LangChain message list for do_summary.

    Serialises all qualifying articles from *payload* into a single prompt so
    the LLM classifies them in one streaming call.  Items shorter than
    ``_MIN_CONTENT_LEN`` are skipped.  The system prompt is built dynamically
    from topic codes loaded from ``fin_markets.news_topics``.

    Args:
        payload: Serialised :class:`DoSummaryInput` dict.

    Returns:
        LangChain message list (SystemMessage + HumanMessage).
    """
    inp = DoSummaryInput.model_validate(payload)
    articles = [NewsArticle.model_validate(a) for a in inp.news_articles]

    parts: list[str] = []
    for article in articles:
        if len(article.content) < _MIN_CONTENT_LEN:
            continue
        url_hash_val = _url_hash(article.url, article.title)
        parts.append(
            f"[{url_hash_val}]\nTitle: {article.title}\nBody:\n{article.content[:3000]}"
        )

    articles_text = "\n\n---\n\n".join(parts)
    topics = _get_topics_sync()
    return _DO_SUMMARY_PROMPT.format_messages(
        system_content=_build_batch_system_prompt(topics),
        articles_text=articles_text,
    )


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_do_summary_prompt}


def _parse_summary_answer(answer_dict: dict, topics: dict[str, str | None]) -> "DoSummaryOutput":
    """Parse and validate the streaming LLM answer into a :class:`DoSummaryOutput`.

    Clamps each per-article field to known reference values; unknown codes fall
    back to safe defaults.  Per-article parse failures are logged as warnings
    and that article is counted as skipped.

    Args:
        answer_dict: Parsed JSON dict from the streaming answer, expected to contain
                     ``{"summaries": {"<url_hash>": {...}, ...}}``.
        topics:      Valid topic codes from ``fin_markets.news_topics``.

    Returns:
        Validated :class:`DoSummaryOutput`.
    """
    raw_summaries: dict = answer_dict.get("summaries", {})
    summaries: dict[str, dict[str, Any]] = {}
    skipped_count = 0

    for url_hash_val, raw in raw_summaries.items():
        try:
            sentiment = raw.get("sentiment_level", "neutral")
            if sentiment not in _SENTIMENT_LEVELS:
                sentiment = "neutral"
            topic = raw.get("topic")
            if topic is not None and topic not in topics:
                topic = None
            summaries[url_hash_val] = SummaryRecord(
                summary=str(raw.get("summary", "")),
                sentiment_level=sentiment,
                topic=topic,
                tags=raw.get("tags", []),
            ).model_dump(mode="json")
        except Exception as exc:
            logger.warning(
                "[%s] failed to parse summary for hash=%r: %s",
                NEWS_TASK_DIGEST_ERROR, url_hash_val[:16], exc,
            )
            skipped_count += 1

    return DoSummaryOutput(summaries=summaries, skipped_count=skipped_count)


# ---------------------------------------------------------------------------
# Per-article record
# ---------------------------------------------------------------------------


class SummaryRecord(BaseModel):
    """Per-article LLM classification output stored in :class:`DoSummaryOutput`.

    Attributes:
        summary:         Content verbatim (<=500 chars) or 2-3 sentence compressed summary.
        sentiment_level: Sentiment code (validated against reference set).
        topic:           Topic code from ``news_topics``, or ``None``.
        tags:            Free-form tag list.
    """

    summary: str = Field(default="", description="Verbatim content or compressed summary.")
    sentiment_level: str = Field(default="neutral", description="Sentiment code.")
    topic: str | None = Field(default=None, description="Topic code from news_topics or null.")
    tags: list[str] = Field(default_factory=list, description="Free-form tag list.")


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class DoSummaryInput(BaseModel):
    """Input for the do_summary task.

    Attributes:
        input_raw_id:    FK to the ``input_raw`` row (for cache look-up and provenance).
        news_articles:   Serialised :class:`~backend.resources.news.models.NewsArticle`
                         dicts from the ``get_news`` output.
        detailed_prompt: Optional detailed prompt to customise the summary task.
    """

    input_raw_id: int | None = Field(default=None, description="FK to input_raw row.")
    news_articles: list[dict[str, Any]] = Field(
        default_factory=list, description="Serialised NewsArticle dicts.",
    )
    detailed_prompt: str | None = Field(
        default=None, description="Optional detailed prompt for the summary task.",
    )


class DoSummaryOutput(BaseModel):
    """Output from the do_summary task.

    Attributes:
        summaries:     Mapping of ``url_hash`` -> serialised :class:`SummaryRecord`
                       for each successfully classified article.
        skipped_count: Number of articles that failed LLM classification.
        from_cache:    ``True`` when summaries were loaded from existing
                       ``news_stats`` rows (LLM call was skipped).
    """

    summaries: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="url_hash -> SummaryRecord dict for each successfully classified article.",
    )
    skipped_count: int = Field(
        default=0, description="Articles that failed classification (warned and skipped)."
    )
    from_cache: bool = Field(default=False, description="True when loaded from existing news_stats rows.")


# ---------------------------------------------------------------------------
# PG cache function
# ---------------------------------------------------------------------------


async def _do_summary_pg_cache(
    inp: DoSummaryInput, ctx: NodeContext
) -> DoSummaryOutput | None:
    """Check pg for existing summaries in news_stats for the given input_raw_id.

    Returns cached summaries when the linked ``input_raw`` row is within the
    4-hour TTL (implicitly guaranteed by ``get_news.pg_cache_fn``).

    Args:
        inp: Typed task input containing the ``input_raw_id``.
        ctx: Current node context (unused; present for signature compatibility).

    Returns:
        ``DoSummaryOutput`` with ``from_cache=True`` on a cache hit, or ``None``.
    """
    if inp.input_raw_id is None:
        return None
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(NewsStatsSQL.GET_SUMMARIES_BY_INPUT_RAW_ID, (inp.input_raw_id,))
        cached_rows = await cur.fetchall()
    if not cached_rows:
        return None
    cached_summaries = {
        row["url_hash"]: SummaryRecord(
            summary=row["summary"] or "",
            sentiment_level=row["sentiment_level"] or "neutral",
            topic=row["topic"],
            tags=list(row["tags"] or []),
        ).model_dump(mode="json")
        for row in cached_rows
    }
    return DoSummaryOutput(summaries=cached_summaries, from_cache=True)


# ---------------------------------------------------------------------------
# LangGraph layer -- @task orchestration
# ---------------------------------------------------------------------------


@task
async def _do_summary_task(
    task_input: TaskInput[DoSummaryInput],
) -> TaskOutput[DoSummaryOutput]:
    """LangGraph @task: classify news articles via the Celery streaming worker.

    The pg cache check is handled upstream by ``run_task`` via ``pg_cache_fn``.
    This function is only reached on a cache miss.

    Fast path (no qualifying content): creates + immediately completes a ToolCall
    task record and returns an empty :class:`DoSummaryOutput`.

    Normal path: creates a Streaming task, delegates to ``run_stream`` via
    ``delegate_stream``, parses the batched JSON answer, and completes the task.
    On exception, marks the task as failed and re-raises so that the seq-level
    wrapper can log a warning and continue without summaries.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`DoSummaryInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`DoSummaryOutput`.
    """
    ctx = task_input.ctx
    inp = task_input.content
    payload = inp.model_dump(mode="json")

    articles = [NewsArticle.model_validate(a) for a in inp.news_articles]

    # No qualifying articles -- ToolCall fast path.
    if not any(len(a.content) >= _MIN_CONTENT_LEN for a in articles):
        output = DoSummaryOutput()
        await create_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
            view_type="ToolCall",
        )
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=output.model_dump(mode="json"),
            view_type="ToolCall",
        )
        return TaskOutput(ctx=ctx, content=output)

    # Streaming path -- LLM classifies all qualifying articles.
    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Streaming",
    )
    try:
        result = await delegate_stream(
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            task_name=ctx.task_name,
            node_name=ctx.node_name,
            payload=payload,
        )
        topics = await _load_news_topics()
        output = _parse_summary_answer(result.get("answer", {}), topics)
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=StreamingTaskOutput(
                thinking=result.get("thinking"),
                answer=output.model_dump(mode="json"),
            ).model_dump(),
            view_type="Streaming",
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Streaming",
        )
        raise


do_summary: NodeTask[DoSummaryInput, DoSummaryOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Streaming LLM-classify and summarise raw news articles: produces summary, "
        "sentiment_level, topic classification, and tags for each article. "
        "Soft-failure task -- streaming failures propagate to the seq wrapper as a warning."
    ),
    input_type=DoSummaryInput,
    output_type=DoSummaryOutput,
    task_fn=_do_summary_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("do_summary runs via the Celery stream worker.")
    ),
    pg_cache_fn=_do_summary_pg_cache,
)

HANDLERS: dict[str, object] = {}

__all__ = [
    "DoSummaryInput",
    "DoSummaryOutput",
    "SummaryRecord",
    "do_summary",
    "STREAM_PROMPT_BUILDERS",
    "HANDLERS",
]
