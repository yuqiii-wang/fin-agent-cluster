"""Handler registry for Celery completion tasks.

Each entry maps a ``task_name`` string (as sent by ``delegate_completion``)
to an *async* callable ``(payload: dict) -> dict``.

``completion_task.run_completion`` imports this registry so that adding a
new handler only requires a new module in this package and an entry here —
no changes to the Celery task itself.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from backend.langgraph.tasks.query import handle_analyze_query
from backend.langgraph.tasks.research import (
    handle_merge_results,
    handle_read_news,
    handle_read_stats,
)

Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]

HANDLERS: dict[str, Handler] = {
    "analyze_query": handle_analyze_query,
    "read_stats": handle_read_stats,
    "read_news": handle_read_news,
    "merge_results": handle_merge_results,
}

__all__ = ["HANDLERS"]
