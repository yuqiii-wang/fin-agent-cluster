"""Celery worker availability check for the celery-ingest pool.

``celery_workers_available()`` pings the worker pool at startup.  If no
workers respond, a warning is emitted so operators know LLM invocations
will fail until at least one worker is reachable.

FastAPI persistence (``fin:llm:completions`` → ``fin_agents.llm_responses``) runs
as a background asyncio task in ``backend.api.background`` regardless of
Celery availability.

Usage (from ``backend.main`` lifespan)
--------------------------------------
    from backend.streaming.fallback import celery_workers_available

    if not await celery_workers_available():
        logger.warning("[streaming] Celery workers not running — LLM calls will fail")
"""

from __future__ import annotations

import asyncio
import logging
import warnings

from backend.streaming.errors import STREAM_FALLBACK_MODE

logger = logging.getLogger(__name__)


async def celery_workers_available(
    timeout: float = 3.0,
    retries: int = 4,
    retry_delay: float = 3.0,
) -> bool:
    """Return ``True`` if the ``celery-ingest`` worker responds to a ping.

    Retries up to *retries* times with *retry_delay* seconds between attempts.

    Args:
        timeout:     Seconds to wait for worker ping replies per attempt.
        retries:     Maximum number of ping attempts.
        retry_delay: Seconds to sleep between failed attempts.

    Returns:
        ``True`` when one or more workers are reachable, ``False`` otherwise.
    """
    loop = asyncio.get_event_loop()
    for attempt in range(1, retries + 1):
        try:
            result = await loop.run_in_executor(None, _sync_ping, timeout)
            if result:
                if attempt > 1:
                    logger.info(
                        "[streaming.fallback] celery-ingest detected on attempt %d/%d",
                        attempt, retries,
                    )
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "[streaming.fallback] celery ping attempt %d/%d failed: %s",
                attempt, retries, exc,
            )
        if attempt < retries:
            logger.debug(
                "[streaming.fallback] celery-ingest not ready yet (attempt %d/%d) — retrying in %.0fs",
                attempt, retries, retry_delay,
            )
            await asyncio.sleep(retry_delay)
    return False


def _sync_ping(timeout: float) -> dict | None:
    """Blocking Celery inspect ping — run in a thread executor.

    Args:
        timeout: Seconds to wait for replies.

    Returns:
        Dict of ``{worker_name: [{ok: pong}]}`` or ``None`` on failure.
    """
    from backend.streaming.celery_app import celery_app  # noqa: PLC0415
    from celery.app.control import DuplicateNodenameWarning

    inspect = celery_app.control.inspect(timeout=timeout)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DuplicateNodenameWarning)
        return inspect.ping()


async def start_fallback_workers() -> list[asyncio.Task]:
    """Warn that Celery workers are unavailable; return empty task list.

    LLM invocations are dispatched to Celery workers via
    :func:`~backend.graph.utils.celery_llm.dispatch_llm`.  If no workers
    are running, those calls will time out.  FastAPI background persistence
    (reading ``fin:llm:completions``) runs independently and is unaffected.

    Returns:
        Empty list (no periodic fallback tasks needed for LLM invocation).
    """
    logger.warning(
        "[%s] celery-ingest workers not detected. "
        "LLM invocations via dispatch_llm will time out until workers start. "
        "Start workers: celery -A backend.streaming.celery_app.celery_app worker "
        "-Q stream:ingest --loglevel=info",
        STREAM_FALLBACK_MODE,
    )
    return []
