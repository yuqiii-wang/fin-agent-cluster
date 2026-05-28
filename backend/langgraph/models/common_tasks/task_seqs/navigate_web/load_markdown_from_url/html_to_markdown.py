"""html_to_markdown — NodeTask: convert raw HTML to Markdown using markitdown.

Accepts a raw HTML string (typically the body returned by ``crawl_url``) and
converts it to clean Markdown text using
`markitdown <https://github.com/microsoft/markitdown>`_.  The HTML is written
to a temporary file so that markitdown's file-based conversion path is used,
which handles encoding correctly and mirrors the approach in ``pdf_to_markdown``.

Design notes
------------
* Conversion is CPU-bound (markitdown/html2text under the hood), so it runs
  inside a ``ThreadPoolExecutor`` to avoid stalling the async event loop.
* No DB persistence — pure in-process transform task.

Execution layers
----------------
LangGraph layer (``_html_to_markdown_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="Markdown")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    1. Writes ``raw_html`` to a UTF-8 temporary ``.html`` file.
    2. Calls ``MarkItDown().convert(tmp_path)`` in a thread executor.
    3. Cleans up the temp file.
    4. Returns serialised :class:`HtmlToMarkdownOutput`.

Public exports
--------------
``html_to_markdown``       — ``NodeTask`` instance.
``HtmlToMarkdownInput``    — Pydantic input model.
``HtmlToMarkdownOutput``   — Pydantic output model.
``HANDLERS``               — dict slice for ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import WEB_TASK_CONVERT_ERROR
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "html_to_markdown"

# Single shared executor — markitdown is CPU-bound.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="html_convert")


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
# Celery layer — business logic
# ---------------------------------------------------------------------------


_STRIP_TAGS: tuple[str, ...] = (
    "head",
    "aside",
    "sidebar",
    "script",
    "style",
    "noscript",
)

# Roles / ids / classes commonly used for sidebars and navigation chrome.
_STRIP_ATTRS_PATTERN = re.compile(
    r'(?:id|class|role)\s*=\s*["\'][^"\']*'
    r'(?:sidebar|side-bar|side_bar|toc|breadcrumb|cookie|banner|advertisement|ad[-_])'
    r'[^"\']*["\']',
    re.IGNORECASE,
)


def _strip_noise_elements(raw_html: str) -> str:
    """Remove non-content HTML elements (head, nav, sidebar, footer, etc.).

    Uses BeautifulSoup when available for robust removal; falls back to a
    regex-based approach for environments without bs4.

    Args:
        raw_html: Original HTML string.

    Returns:
        HTML string with noise elements removed and main content preserved.
    """
    try:
        from bs4 import BeautifulSoup, Tag  # type: ignore[import]

        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove well-known non-content tags entirely.
        for tag_name in _STRIP_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Remove elements whose id/class/role signals non-content chrome.
        for tag in soup.find_all(True):
            if not isinstance(tag, Tag):
                continue
            attrs_str = " ".join(
                f'{k}="{" ".join(v) if isinstance(v, list) else v}"'
                for k, v in (tag.attrs or {}).items()
            )
            if _STRIP_ATTRS_PATTERN.search(attrs_str):
                tag.decompose()

        # Prefer <main> or <article> if present; otherwise keep full body.
        main = soup.find("main") or soup.find("article")
        if main:
            return str(main)
        body = soup.find("body")
        return str(body) if body else str(soup)

    except ImportError:
        # Fallback: strip tags with a simple regex (less precise).
        cleaned = raw_html
        for tag_name in _STRIP_TAGS:
            cleaned = re.sub(
                rf"<{tag_name}[\s>].*?</{tag_name}>",
                "",
                cleaned,
                flags=re.IGNORECASE | re.DOTALL,
            )
        return cleaned


def _convert_html(raw_html: str) -> str:
    """Write raw HTML to a temp file and convert to Markdown via markitdown.

    Strips non-content elements (head, nav, sidebar, footer, etc.) before
    conversion so that the resulting Markdown contains only the main body text.

    Runs synchronously; call inside a thread executor from async context.

    Args:
        raw_html: HTML string to convert.

    Returns:
        Markdown text extracted from the HTML.

    Raises:
        RuntimeError: When markitdown raises any conversion error.
    """
    from markitdown import MarkItDown  # deferred import — optional dependency

    cleaned_html = _strip_noise_elements(raw_html)

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".html",
            encoding="utf-8",
            delete=False,
        ) as tmp:
            tmp.write(cleaned_html)
            tmp_path = tmp.name

        md = MarkItDown()
        result = md.convert(tmp_path)
        return result.text_content or ""
    except Exception as exc:
        raise RuntimeError(
            f"[{WEB_TASK_CONVERT_ERROR}] markitdown HTML conversion failed: {exc}"
        ) from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def _handler(payload: dict) -> dict:
    """Convert raw HTML to Markdown in a thread executor.

    Args:
        payload: Serialised :class:`HtmlToMarkdownInput` dict.

    Returns:
        Serialised :class:`HtmlToMarkdownOutput` dict.

    Raises:
        RuntimeError: markitdown conversion failed.
    """
    inp = HtmlToMarkdownInput.model_validate(payload)
    loop = asyncio.get_event_loop()
    markdown = await loop.run_in_executor(_EXECUTOR, _convert_html, inp.raw_html)
    return HtmlToMarkdownOutput(
        markdown=markdown,
        char_count=len(markdown),
        source_url=inp.source_url,
    ).model_dump()


# ---------------------------------------------------------------------------
# LangGraph layer — @task
# ---------------------------------------------------------------------------


@task
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
