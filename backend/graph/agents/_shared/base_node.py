from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import (
    update_node_execution_status,
    start_node_execution,
    finish_node_execution,
)
from backend.sse_notifications.node import emit_node_input, emit_node_output, emit_node_status

logger = logging.getLogger(__name__)


class BaseNode:
    """Base class for LangGraph nodes with common functionality."""

    node_name: str
    """Unique name for this node (used in logs and events)."""

    def __init__(self):
        if not hasattr(self, "node_name") or not self.node_name:
            raise NotImplementedError("Subclasses must define 'node_name' class attribute")

    async def _execute_node_workflow(
        self,
        thread_id: str,
        parent_node_execution_ids: list[int] | int | None,
        node_input: Any,
        task_runner: Callable,
        pre_execute_hook: Callable | None = None,
        use_start_finish: bool = False,
    ) -> dict:
        """Execute the node workflow including task, emit events, and state update.

        Args:
            thread_id: LangGraph thread ID.
            parent_node_execution_ids: List of parent node execution IDs (or single int for backward compat).
            node_input: Node input model instance or dict.
            task_runner: Async function that runs the actual task(s) - receives
                        (thread_id, node_id, node_execution_id) as first arguments.
            pre_execute_hook: Optional hook to call before emitting node_input,
                            receives (thread_id, node_id) as arguments.
            use_start_finish: Whether to use start_node_execution/finish_node_execution
                            instead of emit_node_input/emit_node_output.

        Returns:
            Dictionary with partial state update.
        """
        # Normalize parent_node_execution_ids
        if isinstance(parent_node_execution_ids, int):
            parent_node_execution_ids = [parent_node_execution_ids]
        elif parent_node_execution_ids is None:
            parent_node_execution_ids = []

        node_id: str = node_input.get("node_id") if isinstance(node_input, dict) else node_input.node_id
        task_id: str = node_input.get("task_id") if isinstance(node_input, dict) else node_input.task_id

        if pre_execute_hook:
            await pre_execute_hook(thread_id, node_id)

        t0 = time.monotonic()

        # Start node execution
        node_execution_id: int
        if use_start_finish:
            started_at = datetime.now(timezone.utc)
            node_execution_id = await start_node_execution(
                thread_id,
                self.node_name,
                node_input,
                started_at,
                node_uuid=node_id,
                parent_node_execution_id=parent_node_execution_ids[0] if parent_node_execution_ids else None,
            )
        else:
            node_execution_id, _ = await emit_node_input(
                thread_id,
                self.node_name,
                node_input.model_dump() if not isinstance(node_input, dict) else node_input,
                node_uuid=node_id,
                parent_node_execution_ids=parent_node_execution_ids,
            )

        await emit_node_status(thread_id, node_id, self.node_name, "running")

        task_result: Any = None
        try:
            task_result = await task_runner(thread_id, node_id, node_execution_id)
        except asyncio.CancelledError:
            await update_node_execution_status(node_execution_id, "cancelled")
            await emit_node_status(thread_id, node_id, self.node_name, "cancelled")
            raise
        except Exception:
            await update_node_execution_status(node_execution_id, "failed")
            await emit_node_status(thread_id, node_id, self.node_name, "failed")
            raise

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        node_output = self._create_node_output(task_result)
        ended_at_ms: int | None = None

        # Finish node execution
        if use_start_finish:
            await finish_node_execution(node_execution_id, node_output.model_dump() if not isinstance(node_output, dict) else node_output, elapsed_ms)
        else:
            ended_at_ms = await emit_node_output(
                thread_id, self.node_name, node_execution_id, node_output.model_dump() if not isinstance(node_output, dict) else node_output, elapsed_ms,
            )

        await emit_node_status(thread_id, node_id, self.node_name, "completed", ended_at_ms=ended_at_ms)

        self._log_completion(task_result, thread_id, node_id, elapsed_ms)
        return self._create_state_update(node_execution_id, node_id, task_id, task_result)

    def _create_node_output(self, task_result: Any) -> Any:
        """Create the node output model from the task result.

        Override this method in subclasses.

        Args:
            task_result: Result from the task runner.

        Returns:
            Node output model instance or dict.
        """
        raise NotImplementedError("Subclasses must implement '_create_node_output'")

    def _log_completion(self, task_result: Any, thread_id: str, node_id: str, elapsed_ms: int) -> None:
        """Log node completion.

        Override this method in subclasses for custom logging.

        Args:
            task_result: Result from the task runner.
            thread_id: LangGraph thread ID.
            node_id: Node UUID.
            elapsed_ms: Elapsed time in milliseconds.
        """
        logger.info(
            "[%s] completed thread_id=%s node_id=%s elapsed_ms=%d",
            self.node_name, thread_id, node_id, elapsed_ms,
        )

    def _create_state_update(
        self,
        node_execution_id: int,
        node_id: str,
        task_id: str,
        task_result: Any,
    ) -> dict:
        """Create the partial state update from the task result.

        Override this method in subclasses.

        Args:
            node_execution_id: Node execution ID.
            node_id: Node UUID.
            task_id: Task ID.
            task_result: Result from the task runner.

        Returns:
            Dictionary with partial state update.
        """
        raise NotImplementedError("Subclasses must implement '_create_state_update'")

    async def __call__(self, state: StreamRunState) -> dict:
        """Execute the node from LangGraph state.

        Override this method in subclasses.

        Args:
            state: LangGraph state.

        Returns:
            Dictionary with partial state update.
        """
        raise NotImplementedError("Subclasses must implement '__call__'")
