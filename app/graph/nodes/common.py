"""Shared node utilities — logging, timing, LLM access, analysis snapshot cache."""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.llm.factory import get_langchain_chat_model

logger = logging.getLogger(__name__)


def get_llm():
    """Get the shared LangChain chat model for agent nodes.

    Returns:
        LangChain ChatModel instance.
    """
    return get_langchain_chat_model()


async def get_cached_analysis(security_id: int | None, node_name: str) -> str | None:
    """Return a fresh cached analysis snapshot from DB, or None.

    Args:
        security_id: FK to fin_markets.securities; skip cache if None.
        node_name: LangGraph node identifier string.

    Returns:
        Cached LLM output text if still fresh, else ``None``.
    """
    if not security_id:
        return None
    try:
        from app.database import _get_session_factory
        from app.db.repos.analysis_snapshots import AnalysisSnapshotRepo

        factory = _get_session_factory()
        async with factory() as session:
            repo = AnalysisSnapshotRepo(session)
            return await repo.get_fresh(security_id, node_name)
    except Exception as exc:
        logger.warning("[%s] analysis cache lookup failed: %s", node_name, exc)
        return None


async def save_analysis_snapshot(
    security_id: int | None,
    node_name: str,
    content: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist an LLM analysis output to fin_strategies.analysis_snapshots.

    Args:
        security_id: FK to fin_markets.securities; skip persist if None.
        node_name: LangGraph node identifier string.
        content: Full LLM output text.
        extra: Optional metadata dict (prompt params, ticker, etc.).
    """
    if not security_id:
        return
    try:
        from app.database import _get_session_factory
        from app.db.repos.analysis_snapshots import AnalysisSnapshotRepo

        factory = _get_session_factory()
        async with factory() as session:
            repo = AnalysisSnapshotRepo(session)
            await repo.save(
                security_id=security_id,
                node_name=node_name,
                content=content,
                extra=extra or {},
            )
    except Exception as exc:
        logger.warning("[%s] analysis snapshot save failed: %s", node_name, exc)


async def log_node_execution(
    thread_id: str,
    node_name: str,
    input_data: dict[str, Any],
    output_data: dict[str, Any],
    started_at: datetime,
    elapsed_ms: int,
) -> None:
    """Persist a node's input/output and elapsed time to fin_agents.node_executions.

    Args:
        thread_id: LangGraph thread correlation ID.
        node_name: Name of the graph node.
        input_data: Node input state snapshot.
        output_data: Node output state snapshot.
        started_at: Timestamp when node execution began.
        elapsed_ms: Wall-clock execution time in milliseconds.
    """
    from app.database import _get_session_factory
    from app.models.agents import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        session.add(
            NodeExecution(
                thread_id=thread_id,
                node_name=node_name,
                input=input_data,
                output=output_data,
                started_at=started_at,
                elapsed_ms=elapsed_ms,
            )
        )
        await session.commit()


class NodeTimer:
    """Context manager for timing node execution.

    Usage:
        timer = NodeTimer()
        with timer:
            result = await llm.ainvoke(...)
        # timer.started_at, timer.elapsed_ms available
    """

    def __init__(self) -> None:
        self.started_at: datetime = datetime.now(timezone.utc)
        self.elapsed_ms: int = 0
        self._t0: float = 0

    def __enter__(self) -> "NodeTimer":
        self.started_at = datetime.now(timezone.utc)
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed_ms = int((time.monotonic() - self._t0) * 1000)
