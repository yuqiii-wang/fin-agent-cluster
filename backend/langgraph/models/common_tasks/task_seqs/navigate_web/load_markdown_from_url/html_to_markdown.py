"""html_to_markdown -- NodeTask: convert raw HTML to Markdown using markitdown.

Accepts a raw HTML string (typically the body returned by ``crawl_url``) and
converts it to clean Markdown text using
`markitdown <https://github.com/microsoft/markitdown>`_.  Uses utilities from
`html_to_markdown_utils` for the actual conversion.

Design notes
------------
* Conversion is CPU-bound (markitdown/html2text under the hood), so it runs
  inside a ``ThreadPoolExecutor`` to avoid stalling the async event loop.
* No DB persistence -- pure in-process transform task.

Execution layers
----------------
LangGraph layer (``_html_to_markdown_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Markdown")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    1. Uses ``transform_html_to_markdown`` from navigation utils.
    2. Returns serialised :class:`HtmlToMarkdownOutput`.

Public exports
--------------
``html_to_markdown``       -- ``NodeTask`` instance.
``HtmlToMarkdownInput``    -- Pydantic input model.
``HtmlToMarkdownOutput``   -- Pydantic output model.
``HANDLERS``               -- dict slice for ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import WEB_TASK_CONVERT_ERROR
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.navigation_utils import (
    transform_html_to_markdown,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "html_to_markdown"

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class HtmlToMarkdownInput(BaseModel):
    """Input for the html_to_markdown task.

    Attributes:
        raw_html:   Full HTML response body as a string.
        source_url: Origin URL of the page, used for display and traceability.
    """

    raw_html: str = Field(description="Full HTML body to convert to Markdown.")
    source_url: str = Field(description="Origin URL of the HTML page (for traceability).")

class HtmlToMarkdownOutput(BaseModel):
    """Output from the html_to_markdown task.

    Attributes:
        markdown:   Clean Markdown text extracted from the HTML.
        char_count: Character count of the markdown string.
        source_url: Echo of the input source URL.
    """

    markdown: str = Field(description="Markdown text converted from the HTML.")
    char_count: int = Field(description="Character count of the converted markdown.")
    source_url: str = Field(description="Origin URL of the page.")

# ---------------------------------------------------------------------------
# Celery layer -- business logic
# ---------------------------------------------------------------------------

async def _handler(payload: dict) -> dict:
    """Convert raw HTML to Markdown using navigation utils.

    Args:
        payload: Serialised :class:`HtmlToMarkdownInput` dict.

    Returns:
        Serialised :class:`HtmlToMarkdownOutput` dict.

    Raises:
        RuntimeError: markitdown conversion failed.
    """
    inp = HtmlToMarkdownInput.model_validate(payload)
    try:
        markdown = await transform_html_to_markdown(inp.raw_html)
    except Exception as exc:
        raise RuntimeError(
            f"[{WEB_TASK_CONVERT_ERROR}] markitdown HTML conversion failed: {exc}"
        ) from exc
    return HtmlToMarkdownOutput(
        markdown=markdown,
        char_count=len(markdown),
        source_url=inp.source_url,
    ).model_dump()

# ---------------------------------------------------------------------------
# LangGraph layer -- @task
# ---------------------------------------------------------------------------

async def _html_to_markdown_task(
    task_input: TaskInput[HtmlToMarkdownInput],
) -> TaskOutput[HtmlToMarkdownOutput]:
    """LangGraph @task: convert HTML to Markdown via the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`HtmlToMarkdownInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`HtmlToMarkdownOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Markdown",
    )
    try:
        result = await delegate_completion(
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            node_id=ctx.node_id,
            node_name=ctx.node_name,
            task_name=ctx.task_name,
            payload=payload,
        )
        output = HtmlToMarkdownOutput.model_validate(result)
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=output.model_dump(mode="json"),
            view_type="Markdown",
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Markdown",
        )
        raise

html_to_markdown: NodeTask[HtmlToMarkdownInput, HtmlToMarkdownOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Convert a raw HTML page body to clean Markdown text using markitdown. "
        "Preserves headings, tables, lists, and inline formatting."
    ),
    input_type=HtmlToMarkdownInput,
    output_type=HtmlToMarkdownOutput,
    task_fn=_html_to_markdown_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "HtmlToMarkdownInput",
    "HtmlToMarkdownOutput",
    "html_to_markdown",
    "HANDLERS",
]
