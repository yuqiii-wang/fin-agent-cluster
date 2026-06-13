"""backend.main_thread.registry -- in-process graph asyncio.Task registry.

Tracks all graph tasks running on this main thread instance so that:
* Graceful shutdown can await them all before closing DB pools.
* Cancel operations can check whether a thread is locally active.

All access is from the uvicorn asyncio event loop, so no locking is required.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# thread_id -> asyncio.Task mapping for all in-flight graph runs.
_tasks: dict[str, asyncio.Task] = {}


def register(thread_id: str, task: asyncio.Task) -> None:
    """Register a graph task and auto-discard it on completion.

    Args:
        thread_id: LangGraph thread UUID.
        task:      asyncio.Task wrapping the graph coroutine.
    """
    _tasks[thread_id] = task
    task.add_done_callback(lambda _: _tasks.pop(thread_id, None))


def is_running(thread_id: str) -> bool:
    """Return ``True`` if the thread has an active (not-done) graph task.

    Args:
        thread_id: LangGraph thread UUID.
    """
    task = _tasks.get(thread_id)
    return task is not None and not task.done()


def get_task(thread_id: str) -> Optional[asyncio.Task]:
    """Return the live graph task for *thread_id*, or ``None``.

    Args:
        thread_id: LangGraph thread UUID.
    """
    return _tasks.get(thread_id)


async def wait_all() -> None:
    """Wait for all in-flight graph tasks to complete.

    Called during FastAPI shutdown to allow running graphs to finish
    before DB pools are closed.
    """
    tasks = list(_tasks.values())
    if not tasks:
        return
    logger.error(
        "[main_thread.registry] waiting for %d in-flight graph(s) to finish",
        len(tasks),
    )
    await asyncio.gather(*tasks, return_exceptions=True)
    _tasks.clear()


__all__ = ["register", "is_running", "get_task", "wait_all"]
