"""CancelHandlerMixin — node/thread cancellation with cascade logic."""

from __future__ import annotations

import logging

from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


class CancelHandlerMixin:
    """Mixin that handles node self-cancellation and thread-level cascade.

    Methods:
        _cancel_self_and_cascade : Cancel this node and cascade to thread if needed.
    """

    async def _cancel_self_and_cascade(
        self,
        thread_id: str,
        node_id: str,
        version: int,
        prev_node_ids: list[str],
        reason: str,
    ) -> GraphState:
        """Cancel this node in the lifecycle layer and cascade to the thread if needed.

        Called when a merge/join node detects that one of its required
        predecessors was cancelled.  Performs:
        1. ``cancel_node`` — DB + SSE (node is already 'running' from upsert_node).
        2. Thread-level cascade — if no active top-level nodes remain, cancels
           the thread (sets Redis cancel flag + DB status).
        3. Returns a ``cancelled`` state delta so LangGraph can finish the
           graph cleanly without raising.

        Args:
            thread_id:      LangGraph thread UUID.
            node_id:        This node's stable ID.
            version:        Fork generation counter.
            prev_node_ids:  Predecessor node IDs.
            reason:         Cancellation reason label.

        Returns:
            GraphState delta with this node marked ``cancelled``.
        """
        from backend.db.postgres import raw_conn
        from backend.langgraph.lifecycle import cancel_node as _lc_cancel_node
        from backend.langgraph.lifecycle import cancel_thread as _lc_cancel_thread
        from backend.langgraph.lifecycle.cancel_flag import set_cancel_flag

        # 1. Cancel in lifecycle (DB → 'cancelled', SSE emitted).
        try:
            await _lc_cancel_node(thread_id, node_id, reason=reason)
        except Exception as exc:
            logger.error(
                "[base_node] auto-cancel DB failed node_id=%s reason=%s: %s",
                node_id, reason, exc,
            )

        # 2. Thread-level cascade: if no active top-level nodes remain, cancel thread.
        try:
            async with raw_conn(readonly=True) as conn:
                cur = await conn.execute(
                    "SELECT COUNT(*) AS cnt FROM fin_agents.nodes "
                    "WHERE thread_id = %s AND parent_node_id IS NULL "
                    "AND status NOT IN ('completed','failed','cancelled','wrong')",
                    (thread_id,),
                )
                row = await cur.fetchone()
            if (row["cnt"] if row else 1) == 0:
                await set_cancel_flag(thread_id)
                await _lc_cancel_thread(thread_id, reason=reason)
        except Exception as exc:
            logger.error(
                "[base_node] auto-cancel cascade failed thread_id=%s: %s",
                thread_id, exc,
            )

        # 3. Return cancelled state delta — do not raise.
        cancelled_record = self._build_node_record(node_id, version, prev_node_ids, "cancelled")  # type: ignore[attr-defined]
        return {"nodes": {node_id: cancelled_record}}

    async def _fail_self_and_cascade(
        self,
        thread_id: str,
        node_id: str,
        version: int,
        prev_node_ids: list[str],
        error: str,
    ) -> GraphState:
        """Fail this node in the lifecycle layer and cascade to the thread if needed.

        Called when a workflow node detects that one of its required predecessors
        failed.  Performs:
        1. ``complete_node(failed=True)`` — DB + SSE.
        2. Thread-level cascade — if no active top-level nodes remain, fails
           the thread (DB status + SSE).
        3. Returns a ``failed`` state delta so LangGraph can finish the graph
           cleanly without raising.

        Args:
            thread_id:      LangGraph thread UUID.
            node_id:        This node's stable ID.
            version:        Fork generation counter.
            prev_node_ids:  Predecessor node IDs.
            error:          Error message describing why the node failed.

        Returns:
            GraphState delta with this node marked ``failed``.
        """
        from backend.db.postgres import raw_conn
        from backend.langgraph.lifecycle import complete_node as _lc_complete_node
        from backend.langgraph.lifecycle import complete_thread as _lc_complete_thread

        # 1. Fail in lifecycle (DB → 'failed', SSE emitted).
        try:
            await _lc_complete_node(
                thread_id=thread_id,
                node_id=node_id,
                node_name=self.node_name,  # type: ignore[attr-defined]
                failed=True,
                error=error,
            )
        except Exception as exc:
            logger.error(
                "[base_node] auto-fail DB failed node_id=%s error=%s: %s",
                node_id, error, exc,
            )

        # 2. Thread-level cascade: if no active top-level nodes remain, fail thread.
        try:
            async with raw_conn(readonly=True) as conn:
                cur = await conn.execute(
                    "SELECT COUNT(*) AS cnt FROM fin_agents.nodes "
                    "WHERE thread_id = %s AND parent_node_id IS NULL "
                    "AND status NOT IN ('completed','failed','cancelled','wrong')",
                    (thread_id,),
                )
                row = await cur.fetchone()
            if (row["cnt"] if row else 1) == 0:
                await _lc_complete_thread(thread_id=thread_id, failed=True, error=error)
        except Exception as exc:
            logger.error(
                "[base_node] auto-fail cascade failed thread_id=%s: %s",
                thread_id, exc,
            )

        # 3. Return failed state delta — do not raise.
        failed_record = self._build_node_record(node_id, version, prev_node_ids, "failed")  # type: ignore[attr-defined]
        return {"nodes": {node_id: failed_record}}


__all__ = ["CancelHandlerMixin"]
