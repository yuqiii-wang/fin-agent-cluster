"""FastAPI-native stream consumer fallback.

When Celery workers are not running this module spawns lightweight asyncio
background tasks that perform the same stream-polling work the Celery workers
would do.  A ``WARNING`` is emitted at startup so operators know they are in
degraded mode.

Design
------
Each ``_poll_*`` coroutine mirrors the corresponding Celery worker task but
runs inside FastAPI's asyncio event loop instead of a separate process.  They
are started from the lifespan context manager and cancelled on shutdown.

Celery detection
----------------
:func:`celery_workers_available` tries to ping active Celery workers via the
broker using ``app.control.inspect(timeout)``.  This is a blocking RPC so it
runs in the default thread executor.

Usage (from ``backend.main`` lifespan)
--------------------------------------
    from backend.streaming.fallback import start_fallback_workers, celery_workers_available

    if not await celery_workers_available():
        logger.warning("[streaming] Celery workers not running — using FastAPI native threads")
        fallback_tasks = await start_fallback_workers()
    ...
    # on shutdown:
    for t in fallback_tasks:
        t.cancel()
"""

from __future__ import annotations

import asyncio
import logging
import warnings
from typing import Any

from backend.streaming.config import ACTIVE_TOPICS, GRAPH_EVENTS, MARKET_TICKS, TRADE_SIGNALS

logger = logging.getLogger(__name__)

# Fallback poll intervals are read from config — see backend.streaming.config.
# Direct references here make the dependency explicit for debuggability.
_GRAPH_POLL_INTERVAL: float = GRAPH_EVENTS.fallback_interval
_MARKET_POLL_INTERVAL: float = MARKET_TICKS.fallback_interval
_SIGNALS_POLL_INTERVAL: float = TRADE_SIGNALS.fallback_interval


async def celery_workers_available(
    timeout: float = 3.0,
    retries: int = 4,
    retry_delay: float = 3.0,
) -> bool:
    """Return ``True`` if at least one Celery worker responds to a ping.

    Retries up to *retries* times with *retry_delay* seconds between attempts.
    On Windows with ``--pool=solo`` the worker subprocess takes 10-15 seconds
    to spawn, load modules, and register with the broker.  A single-shot ping
    with a 3-second timeout therefore always fails at startup.

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
            result: Any = await loop.run_in_executor(None, _sync_ping, timeout)
            if result:
                if attempt > 1:
                    logger.info(
                        "[streaming.fallback] celery workers detected on attempt %d/%d",
                        attempt, retries,
                    )
                return True
        except Exception as exc:
            logger.debug(
                "[streaming.fallback] celery ping attempt %d/%d failed: %s",
                attempt, retries, exc,
            )
        if attempt < retries:
            logger.debug(
                "[streaming.fallback] celery not ready yet (attempt %d/%d) — retrying in %.0fs",
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
    from backend.streaming.celery_app import celery_app
    from celery.app.control import DuplicateNodenameWarning

    inspect = celery_app.control.inspect(timeout=timeout)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DuplicateNodenameWarning)
        return inspect.ping()


# ---------------------------------------------------------------------------
# Fallback poll loops — asyncio coroutines mirroring Celery workers
# ---------------------------------------------------------------------------


async def _poll_graph_events() -> None:
    """Asyncio loop that continuously drains ``fin:graph:events``.

    Runs indefinitely until cancelled; each iteration processes a small batch
    then sleeps ``_GRAPH_POLL_INTERVAL`` seconds.
    """
    from backend.streaming.workers.graph_events import _consume

    logger.info("[streaming.fallback] starting native graph-events consumer")
    while True:
        try:
            await _consume()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[streaming.fallback] graph_events error: %s", exc)
        await asyncio.sleep(_GRAPH_POLL_INTERVAL)
    logger.info("[streaming.fallback] graph-events consumer stopped")


async def _poll_market_data() -> None:
    """Asyncio loop that continuously drains ``fin:market:ticks``.

    Runs indefinitely until cancelled.
    """
    from backend.streaming.workers.market_data import _consume

    logger.info("[streaming.fallback] starting native market-data consumer")
    while True:
        try:
            await _consume()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[streaming.fallback] market_data error: %s", exc)
        await asyncio.sleep(_MARKET_POLL_INTERVAL)
    logger.info("[streaming.fallback] market-data consumer stopped")


async def _poll_signals() -> None:
    """Asyncio loop that continuously drains ``fin:signals:trade``.

    Runs indefinitely until cancelled.
    """
    from backend.streaming.workers.signals import _consume

    logger.info("[streaming.fallback] starting native trade-signals consumer")
    while True:
        try:
            await _consume()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[streaming.fallback] signals error: %s", exc)
        await asyncio.sleep(_SIGNALS_POLL_INTERVAL)
    logger.info("[streaming.fallback] trade-signals consumer stopped")


async def start_fallback_workers() -> list[asyncio.Task]:
    """Spawn all stream-poll background tasks in the current event loop.

    Should be called from the FastAPI lifespan context manager **only after**
    :func:`celery_workers_available` has returned ``False``.

    Returns:
        List of :class:`asyncio.Task` objects.  Store them and call
        ``task.cancel()`` for each during application shutdown.
    """
    tasks = [
        asyncio.create_task(_poll_graph_events(), name="fallback-graph-events"),
        asyncio.create_task(_poll_market_data(),   name="fallback-market-data"),
        asyncio.create_task(_poll_signals(),        name="fallback-trade-signals"),
    ]
    logger.warning(
        "[streaming] FALLBACK MODE: Celery workers not detected. "
        "Stream consumers running as FastAPI background threads. "
        "Start Celery for production-grade durability: "
        "celery -A backend.streaming.celery_app.celery_app worker --beat --loglevel=info"
    )
    return tasks
