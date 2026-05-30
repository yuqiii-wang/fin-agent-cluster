"""propose_web_knowledge_urls — NodeTask: map an equity symbol to financial knowledge URLs.

Given a ticker symbol, constructs the canonical URL for finding derivatives,
options chain, and related financial market data on Yahoo Finance.

Execution layers
----------------
LangGraph layer (``_propose_web_knowledge_urls_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Json")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    Validates the symbol and returns the Yahoo Finance options URL for the
    given ticker.  No external network call is made.

Public exports
--------------
``propose_web_knowledge_urls``      — ``NodeTask`` instance.
``ProposeWebKnowledgeUrlsInput``    — Pydantic input model.
``ProposeWebKnowledgeUrlsOutput``   — Pydantic output model.
``HANDLERS``                        — dict slice for ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import logging

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import WEB_KNOWLEDGE_URL_NO_SYMBOL
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "propose_web_knowledge_urls"

_YAHOO_OPTIONS_URL = "https://finance.yahoo.com/quote/{symbol}/options/"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class ProposeWebKnowledgeUrlsInput(BaseModel):
    """Input for the propose_web_knowledge_urls task.

    Attributes:
        symbol: Equity ticker symbol, e.g. ``'AAPL'``.
    """

    symbol: str = Field(description="Equity ticker symbol, e.g. 'AAPL'.")


class ProposeWebKnowledgeUrlsOutput(BaseModel):
    """Output from the propose_web_knowledge_urls task.

    Attributes:
        symbol: Normalised (uppercase) equity ticker symbol.
        url:    Primary URL for derivatives and options knowledge for this symbol.
    """

    symbol: str = Field(description="Normalised equity ticker symbol.")
    url: str = Field(description="Primary URL for derivatives/options data for this symbol.")


# ---------------------------------------------------------------------------
# Celery layer — pure business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Construct the Yahoo Finance options URL for the given symbol.

    Args:
        payload: Serialised :class:`ProposeWebKnowledgeUrlsInput` dict.

    Returns:
        Serialised :class:`ProposeWebKnowledgeUrlsOutput` dict.

    Raises:
        ValueError: When no symbol is provided.
    """
    inp = ProposeWebKnowledgeUrlsInput.model_validate(payload)
    symbol = inp.symbol.strip().upper()
    if not symbol:
        raise ValueError(
            f"[{WEB_KNOWLEDGE_URL_NO_SYMBOL}] symbol must be a non-empty ticker string."
        )
    url = _YAHOO_OPTIONS_URL.format(symbol=symbol)
    return ProposeWebKnowledgeUrlsOutput(symbol=symbol, url=url).model_dump(mode="json")


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _propose_web_knowledge_urls_task(
    task_input: TaskInput[ProposeWebKnowledgeUrlsInput],
) -> TaskOutput[ProposeWebKnowledgeUrlsOutput]:
    """LangGraph @task: delegates propose_web_knowledge_urls to the Celery completion worker.

    Constructs the canonical Yahoo Finance options URL for the given equity
    symbol.  No external network request is made in this task; the URL is
    passed to a downstream ``navigate_web`` pipeline.

    Args:
        task_input: Typed envelope with TaskContext and ProposeWebKnowledgeUrlsInput content.

    Returns:
        TaskOutput wrapping ProposeWebKnowledgeUrlsOutput with the proposed URL.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Json",
    )
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload
        )
        output = ProposeWebKnowledgeUrlsOutput.model_validate(result)
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=output.model_dump(mode="json"),
            view_type="Json",
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        logger.error(
            "[%s] propose_web_knowledge_urls failed for symbol=%r: %s",
            WEB_KNOWLEDGE_URL_NO_SYMBOL, task_input.content.symbol, exc,
        )
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Json",
        )
        raise


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

propose_web_knowledge_urls = NodeTask(
    name=_TASK_NAME,
    description=(
        "Map an equity symbol to a financial market knowledge URL. "
        "Returns the Yahoo Finance options page URL for the given ticker, "
        "to be consumed by a downstream navigate_web pipeline."
    ),
    input_type=ProposeWebKnowledgeUrlsInput,
    output_type=ProposeWebKnowledgeUrlsOutput,
    task_fn=_propose_web_knowledge_urls_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "propose_web_knowledge_urls",
    "ProposeWebKnowledgeUrlsInput",
    "ProposeWebKnowledgeUrlsOutput",
    "HANDLERS",
]
