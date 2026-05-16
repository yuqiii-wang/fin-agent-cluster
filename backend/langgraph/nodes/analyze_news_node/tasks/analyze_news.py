"""analyze_news — NodeTask for analyze_news_node.

Execution layers
----------------
LangGraph layer (``_analyze_news_task``):
    Calls ``create_task``, delegates to a Celery completion worker via
    ``delegate_completion``, and calls ``complete_task`` on success / failure.

Celery layer (``_handler``):
    Performs rule-based sentiment analysis on news articles produced by
    research_subgraph: scores each article title by positive/negative
    keyword presence, aggregates a [-1.0, 1.0] sentiment score, and
    extracts the most notable headlines as highlights.
"""

from __future__ import annotations

import logging

from langgraph.func import task

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.nodes.base.models import TaskInput, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.analyze_news_node.models import AnalyzeNewsInput, AnalyzeNewsOutput
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_TASK_NAME = "analyze_news"

_POSITIVE_WORDS = frozenset({
    "beat", "beats", "surge", "surges", "rally", "rallies", "gain", "gains",
    "profit", "profits", "growth", "upgrade", "upgraded", "record", "high",
    "strong", "positive", "bullish", "outperform", "rises", "rose", "up",
})
_NEGATIVE_WORDS = frozenset({
    "miss", "misses", "fall", "falls", "drop", "drops", "loss", "losses",
    "decline", "declines", "downgrade", "downgraded", "low", "weak",
    "negative", "bearish", "underperform", "cut", "cuts", "down", "plunge",
    "plunges", "concern", "concerns", "risk", "risks",
})


def _score_title(title: str) -> float:
    """Return a simple sentiment score in [-1.0, 1.0] for a news title.

    Args:
        title: Article headline string.

    Returns:
        Positive float for bullish language, negative for bearish, 0 for neutral.
    """
    words = set(title.lower().split())
    pos = len(words & _POSITIVE_WORDS)
    neg = len(words & _NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


async def _handler(payload: dict) -> dict:
    """Analyse news articles to compute sentiment score and highlights.

    Args:
        payload: Serialised ``AnalyzeNewsInput`` dict.

    Returns:
        Serialised ``AnalyzeNewsOutput`` dict.
    """
    inp = AnalyzeNewsInput.model_validate(payload)
    news_data = inp.news_data
    symbol = news_data.get("symbol", "")
    articles: list[dict] = news_data.get("articles", [])

    if not articles:
        return AnalyzeNewsOutput(
            symbol=symbol,
            news_sentiment=f"No news articles found for {symbol}.",
            sentiment_score=0.0,
            highlights=[],
        ).model_dump()

    scored = [(a, _score_title(a.get("title", ""))) for a in articles]
    aggregate = sum(s for _, s in scored) / len(scored)

    # Highlights: top 3 articles by absolute score, preferring non-zero
    sorted_articles = sorted(scored, key=lambda x: abs(x[1]), reverse=True)
    highlights = [
        a.get("title", "")
        for a, _ in sorted_articles[:3]
        if a.get("title")
    ]

    if aggregate > 0.15:
        sentiment_label = "positive"
    elif aggregate < -0.15:
        sentiment_label = "negative"
    else:
        sentiment_label = "neutral"

    narrative = (
        f"News sentiment for {symbol} is {sentiment_label} "
        f"(score: {aggregate:+.2f}) based on {len(articles)} article(s). "
    )
    if highlights:
        narrative += f"Key headline: \"{highlights[0]}\"."

    return AnalyzeNewsOutput(
        symbol=symbol,
        news_sentiment=narrative,
        sentiment_score=round(aggregate, 4),
        highlights=highlights,
    ).model_dump()


@task
async def _analyze_news_task(
    task_input: TaskInput[AnalyzeNewsInput],
) -> TaskOutput[AnalyzeNewsOutput]:
    """LangGraph @task: delegates analyze_news to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and AnalyzeNewsInput content.

    Returns:
        TaskOutput wrapping AnalyzeNewsOutput.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload)
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise
    output = AnalyzeNewsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


analyze_news = NodeTask(
    name=_TASK_NAME,
    description=(
        "Analyse news articles to produce an aggregate sentiment score, "
        "sentiment narrative, and key headline highlights for the equity symbol."
    ),
    input_type=AnalyzeNewsInput,
    output_type=AnalyzeNewsOutput,
    task_fn=_analyze_news_task,
    handler=_handler,
)
