"""pdf_to_markdown -- NodeTask: convert a PDF file or URL to Markdown using markitdown.

Accepts either a local file path or an HTTP/HTTPS URL pointing to a PDF document
and returns the full Markdown text extracted by
`markitdown <https://github.com/microsoft/markitdown>`_.

Design notes
------------
* markitdown is used as the conversion engine; it preserves headings, tables,
  lists, and inline formatting better than plain text extractors.
* No DB persistence -- this is a pure in-process transform task.
* The Celery layer runs synchronously inside an async executor so that the
  blocking markitdown I/O does not stall the event loop.

Execution layers
----------------
LangGraph layer (``_pdf_to_markdown_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Markdown")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    1. Validates the source (file path must exist; URL must be http/https).
    2. Calls ``MarkItDown().convert(source)`` in a thread executor.
    3. Returns serialised ``PdfToMarkdownOutput``.

Public exports
--------------
``pdf_to_markdown``      -- ``NodeTask`` instance.
``PdfToMarkdownInput``   -- Pydantic input model.
``PdfToMarkdownOutput``  -- Pydantic output model.
``HANDLERS``             -- dict slice for ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field, field_validator

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    PDF_TASK_CONVERT_ERROR,
    PDF_TASK_SOURCE_NOT_FOUND,
    PDF_TASK_INVALID_SOURCE,
)
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "pdf_to_markdown"

# Single shared executor -- markitdown conversion is CPU-bound (pdfminer under the hood).
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pdf_convert")

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class PdfToMarkdownInput(BaseModel):
    """Input for the pdf_to_markdown task.

    Attributes:
        source: Local absolute file path or HTTP/HTTPS URL pointing to a PDF document.
    """

    source: str = Field(description="Absolute file path or HTTP/HTTPS URL of the PDF to convert.")

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        """Reject obviously invalid sources at model-validation time."""
        v = v.strip()
        if not v:
            raise ValueError("source must not be empty")
        return v

class PdfToMarkdownOutput(BaseModel):
    """Output from the pdf_to_markdown task.

    Attributes:
        markdown:   Full Markdown text extracted from the PDF.
        char_count: Length of the extracted markdown string (useful for quick size checks).
        source:     Echo of the input source for traceability.
    """

    markdown: str = Field(description="Markdown text extracted from the PDF.")
    char_count: int = Field(description="Character count of the extracted markdown.")
    source: str = Field(description="Input source that was converted.")

# ---------------------------------------------------------------------------
# Celery layer -- business logic
# ---------------------------------------------------------------------------

def _convert(source: str) -> str:
    """Run markitdown conversion synchronously (called inside a thread executor).

    Args:
        source: Absolute file path or HTTP/HTTPS URL.

    Returns:
        Markdown text extracted from the PDF.

    Raises:
        FileNotFoundError: When *source* is a local path that does not exist.
        ValueError:        When *source* is not a valid file path or http/https URL.
        RuntimeError:      When markitdown raises any conversion error.
    """
    from markitdown import MarkItDown  # deferred import -- optional dependency

    is_url = source.startswith("http://") or source.startswith("https://")
    if not is_url:
        if not os.path.isabs(source):
            raise ValueError(f"[{PDF_TASK_INVALID_SOURCE}] source must be an absolute path or http/https URL: {source!r}")
        if not os.path.isfile(source):
            raise FileNotFoundError(f"[{PDF_TASK_SOURCE_NOT_FOUND}] PDF file not found: {source!r}")

    try:
        md = MarkItDown()
        result = md.convert(source)
        return result.text_content or ""
    except Exception as exc:
        raise RuntimeError(f"[{PDF_TASK_CONVERT_ERROR}] markitdown conversion failed: {exc}") from exc

async def _handler(payload: dict) -> dict:
    """Convert a PDF to Markdown in a thread executor.

    Args:
        payload: Serialised :class:`PdfToMarkdownInput` dict.

    Returns:
        Serialised :class:`PdfToMarkdownOutput` dict.

    Raises:
        FileNotFoundError: PDF file not found at the given path.
        ValueError:        Invalid source (not abs path or http/https URL).
        RuntimeError:      markitdown conversion failed.
    """
    inp = PdfToMarkdownInput.model_validate(payload)
    loop = asyncio.get_event_loop()
    markdown = await loop.run_in_executor(_EXECUTOR, _convert, inp.source)
    return PdfToMarkdownOutput(
        markdown=markdown,
        char_count=len(markdown),
        source=inp.source,
    ).model_dump()

# ---------------------------------------------------------------------------
# LangGraph layer -- @task orchestration
# ---------------------------------------------------------------------------

async def _pdf_to_markdown_task(
    task_input: TaskInput[PdfToMarkdownInput],
) -> TaskOutput[PdfToMarkdownOutput]:
    """LangGraph @task: delegates pdf_to_markdown to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`PdfToMarkdownInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`PdfToMarkdownOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Markdown",
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

    output = PdfToMarkdownOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)

# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

pdf_to_markdown = NodeTask(
    name=_TASK_NAME,
    description=(
        "Convert a PDF document (local absolute file path or HTTP/HTTPS URL) to Markdown text "
        "using markitdown.  Preserves headings, tables, and lists.  Returns the full Markdown "
        "string, its character count, and the input source for traceability."
    ),
    input_type=PdfToMarkdownInput,
    output_type=PdfToMarkdownOutput,
    task_fn=_pdf_to_markdown_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = ["pdf_to_markdown", "PdfToMarkdownInput", "PdfToMarkdownOutput", "HANDLERS"]
