"""Sandbox session lifecycle -- delegates to the sharded sandbox runner service.

Each agent node execution maps to a workdir inside the appropriate
``sandbox-runner-N`` container.  Routing uses the same SHA-256 shard pattern
as Redis and Centrifugo::

    shard_index = SHA-256(thread_id) % len(SANDBOX_RUNNER_NODES)

This guarantees that ``start_session``, every ``run_sandbox`` task, and
``end_session`` for the same thread all target the same container.

Lifecycle
---------
``start_node_session`` -- called by ``BaseNode.orchestrate`` before
    ``build_agent`` is invoked.  POSTs ``/session/{node_id}`` to create the
    workdir inside the container.
``end_node_session``   -- called in the ``orchestrate`` finally block.
    DELETEs ``/session/{node_id}``; errors are logged and suppressed so
    cleanup never masks the underlying node exception.
"""

from __future__ import annotations

__all__ = ["start_node_session", "end_node_session"]


async def start_node_session(node_id: str, thread_id: str) -> None:
    """Create the sandbox workdir for an agent node execution on the correct runner shard.

    Args:
        node_id:   Unique node execution ID (UUID5 keyed by thread + name + version).
        thread_id: LangGraph thread UUID used for shard routing.

    Raises:
        SandboxRunnerError: If the HTTP call to the runner fails.
    """
    from backend.config import get_settings  # noqa: PLC0415
    from backend.sandbox.client import start_runner_session  # noqa: PLC0415

    settings = get_settings()
    await start_runner_session(thread_id, node_id, settings.SANDBOX_RUNNER_NODES)


async def end_node_session(node_id: str, thread_id: str) -> None:
    """Delete the sandbox workdir for an agent node execution on the correct runner shard.

    Called unconditionally in the finally block of ``BaseNode.orchestrate``.
    Errors are logged inside :func:`~backend.sandbox.client.end_runner_session`
    and never re-raised so cleanup does not mask node exceptions.

    Args:
        node_id:   Unique node execution ID.
        thread_id: LangGraph thread UUID used for shard routing.
    """
    from backend.config import get_settings  # noqa: PLC0415
    from backend.sandbox.client import end_runner_session  # noqa: PLC0415

    settings = get_settings()
    await end_runner_session(thread_id, node_id, settings.SANDBOX_RUNNER_NODES)
