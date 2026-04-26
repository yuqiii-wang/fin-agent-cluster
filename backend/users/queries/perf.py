"""Service logic for the perf-test stable-ingest signal endpoint."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def perf_stable_signal(thread_id: str) -> dict[str, str]:
    """Signal that the concurrency perf stream has reached stable TPS.

    Sets the ``stable`` flag on the active
    :class:`~backend.graph.agents.perf_test.tasks.fanout_to_streams._ConcurrentProgress`
    for this thread.  The ingest loop exits at the next batch boundary, appends
    the sentinel, and returns ``(produced, "stable")`` so the node emits
    ``perf_test_complete`` (not ``perf_test_stopped``) to the SSE client.

    Fire-and-forget — returns immediately without waiting for shutdown.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``{"thread_id": ..., "status": "stable_signaled"}`` if found, or
        ``{"thread_id": ..., "status": "not_found"}`` if the timeout already
        fired and the gather has returned.
    """
    # Lazy import — only loaded when a concurrency perf test is active.
    from backend.graph.agents.perf_test.tasks.fanout_to_streams import signal_stable_ingest  # noqa: PLC0415

    found = signal_stable_ingest(thread_id)
    logger.info(
        "[perf] perf_stable_signal thread_id=%s found=%s",
        thread_id,
        found,
    )
    return {"thread_id": thread_id, "status": "stable_signaled" if found else "not_found"}
