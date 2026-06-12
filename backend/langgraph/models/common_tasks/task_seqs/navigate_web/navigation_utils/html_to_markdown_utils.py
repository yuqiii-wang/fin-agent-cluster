"""html_to_markdown_utils — convert a raw HTML string to Markdown using markitdown.

This module exposes a single async helper, :func:`transform_html_to_markdown`,
used by the various ``navigate_web`` nodes that need to go from rendered HTML
to clean Markdown text.

Design notes
------------
* ``markitdown`` is used because it handles real-world HTML well: it preserves
  headings, tables, lists, and inline formatting while stripping boilerplate.
* The conversion is synchronous / CPU-bound in ``markitdown``, so the helper
  offloads the work to a shared ``ThreadPoolExecutor`` to keep the async
  event loop responsive.
* ``markitdown`` is imported lazily so the module can still be imported in
  environments where the optional dependency is missing (a clear ``RuntimeError``
  is raised at call time instead).
"""

from __future__ import annotations

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor

from backend.langgraph.models.common_tasks.errors.codes import WEB_TASK_CONVERT_ERROR

_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="html_convert",
)


def _html_to_markdown_sync(raw_html: str) -> str:
    """Synchronous markitdown conversion — runs inside a thread executor.

    Args:
        raw_html: Raw HTML document string (typically the full ``<html>...</html>``
                  body returned by a crawler / browser).

    Returns:
        Markdown text extracted from *raw_html*.

    Raises:
        RuntimeError: If ``markitdown`` is not installed or the conversion fails.
    """
    try:
        from markitdown import MarkItDown, StreamInfo  # deferred import — optional dependency
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            f"[{WEB_TASK_CONVERT_ERROR}] markitdown is not installed; "
            "install it with `pip install markitdown`."
        ) from exc

    try:
        stream = io.BytesIO(raw_html.encode("utf-8"))
        info = StreamInfo(mimetype="text/html")
        md = MarkItDown()
        result = md.convert(stream, stream_info=info)
        return result.text_content or ""
    except Exception as exc:
        raise RuntimeError(
            f"[{WEB_TASK_CONVERT_ERROR}] markitdown HTML conversion failed: {exc}"
        ) from exc


async def transform_html_to_markdown(raw_html: str) -> str:
    """Convert a raw HTML string to a clean Markdown string using markitdown.

    The actual conversion runs in a shared thread executor to avoid blocking
    the asyncio event loop.

    Args:
        raw_html: Raw HTML document to convert.

    Returns:
        Markdown text extracted from *raw_html*.

    Raises:
        RuntimeError: If ``markitdown`` is not installed or the conversion fails.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_EXECUTOR, _html_to_markdown_sync, raw_html)


__all__ = ["transform_html_to_markdown"]
