"""Shared output model for streaming LangGraph tasks.

Every streaming task (view_type="Streaming") must store output in this shape
so the Hybrid view rendered by the frontend can find the ``thinking`` and
``answer`` fields via the view_schema ``{"thinking": "Markdown", "answer": "Json"}``.

Usage in a @task function
-------------------------
::

    output = MyTaskOutput(field=...)
    await complete_task(
        ...,
        output_data=StreamingTaskOutput(
            thinking=result.get("thinking"),
            answer=output.model_dump(),
        ).model_dump(),
        view_type="Streaming",
    )
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["StreamingTaskOutput"]


class StreamingTaskOutput(BaseModel):
    """Typed output envelope for streaming LangGraph tasks.

    The frontend Hybrid view queries ``output.thinking`` (rendered as Markdown)
    and ``output.answer`` (rendered as Json).  Both fields must exist in the
    task_executions row for the view to render correctly.

    Attributes:
        thinking: Raw ``<think>…</think>`` content extracted by the stream
            worker, or ``None`` when the model did not emit a thinking block.
        answer:   Task-specific result dict (e.g.
            ``{"stock_name": "AAPL", "not_seen": False}`` for analyze_query).
    """

    thinking: str | None = Field(default=None, description="Extracted thinking block, or None.")
    answer: dict[str, Any] = Field(
        default_factory=dict, description="Task-specific result dict."
    )
