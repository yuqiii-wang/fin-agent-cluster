"""Graph runner -- async execution of the LangGraph workflow in the FastAPI event loop.

Each query runs as an ``asyncio.Task`` inside the FastAPI uvicorn event loop.
The graph is a two-level structure:

    POST /api/v1/users/query
      |_ queries.py
           |_ asyncio.create_task(run_graph_async(...))   [FastAPI event loop]
                |_ graph.ainvoke(...)
                     |_ stream_subgraph  (triggered by "DO STREAMING PERFORMANCE TEST NOW")
                     |    |_ mock_runner -> dispatch_throughput_ingest / dispatch_scheduled_ingest -> Celery -> Centrifugo
                     |_ fin_analyst_subgraph  (all other queries)
                          |_ fin_analyst_runner

Lifecycle events
----------------
``started / completed / failed`` are written to PostgreSQL and published to
Redis Pub/Sub by the agent utilities.  The ``done`` terminal event is emitted
here after the graph finishes.

Cancellation
------------
Cancel requests come from ``POST /api/v1/users/query/{thread_id}/cancel``.
Cancel stops the asyncio.Task immediately (CancelledError), yields empty
output, and does NOT trigger resume.

Pause / Resume
--------------
Pause requests come from ``POST /api/v1/users/query/{thread_id}/pause``.
A Redis pause signal is set; the runner detects it at the next LangGraph
``interrupt()`` checkpoint and declines to auto-resume.  The graph state is
persisted by the ``AsyncPostgresSaver`` checkpointer at the interrupt boundary.
The DB status transitions to ``'paused'`` and a ``done(paused)`` SSE event is
emitted.  Calling ``run_resume_from_pause_async`` resumes with
``Command(resume=True)`` so the interrupted node continues without re-running
from scratch.

Interrupts (human-in-the-loop)
-------------------------------
Nodes call ``interrupt(value)`` from ``langgraph.types`` at step-approval
checkpoints.  ``graph.ainvoke()`` returns the current state with an
``__interrupt__`` key when execution is paused.  The runner auto-approves
every interrupt **unless** a pause signal is pending (see above).
See :func:`_invoke_with_auto_approve`.

Checkpoints & resume
---------------------
The ``AsyncPostgresSaver`` checkpointer saves graph state:
- *Before* each node is entered — so ``input=None`` (or ``Command(resume=…)``)
  resumes from the last saved state.
- After ``@task``-decorated subtask results — so ``@task`` bodies are
  *never* re-executed on resume; LangGraph replays their cached outputs.

Calling ``graph.ainvoke(Command(resume=True), config)`` resumes a *paused*
graph from the interrupt checkpoint — the interrupted node continues.
Calling ``graph.ainvoke(None, config)`` resumes a *cancelled/crashed* graph
from the last pre-node checkpoint — the node re-runs from scratch.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from langgraph.types import Command

from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.session.pause_signal import check_and_consume_pause_signal, delete_pause_signal
from backend.db.redis.session.query_phase import set_query_phase
from backend.db.redis.lock_manager.session_cleanup import cleanup_thread_session
from backend.graph.compiled import get_compiled_graph
from backend.graph.models import AgentTask
from backend.sse_notifications import emit_done, publish_task_lifecycle
from backend.graph.governance import publish_governance_end
from backend.streaming.errors import GRAPH_EXECUTION_FAILED
from backend.sse_notifications.thread import emit_query_status
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)


async def _invoke_with_auto_approve(
    graph: Any,
    initial_input: Any,
    config: dict,
) -> dict:
    """Invoke a LangGraph graph, auto-approving ``interrupt()`` checkpoints unless paused.

    Nodes call ``interrupt(value)`` from ``langgraph.types`` to pause execution
    at a step-approval boundary.  ``ainvoke`` returns the current state with
    an ``__interrupt__`` key when such a pause occurs.  This helper normally
    resumes immediately with ``Command(resume=True)`` in a loop.

    **Pause semantics**: when a Redis pause signal is present for *thread_id*
    (set by ``POST /query/{thread_id}/pause``) the signal is consumed and the
    function returns the state **with** ``__interrupt__`` intact.  The caller
    detects the ``__interrupt__`` key and transitions the DB status to
    ``'paused'``, emitting a ``done(paused)`` SSE event.  The LangGraph
    ``AsyncPostgresSaver`` has already persisted the interrupt checkpoint so
    ``Command(resume=True)`` can restore it later.

    A cancelled ``asyncio.Task`` (triggered by ``cancel_query``) propagates
    naturally — ``CancelledError`` is raised from the ``ainvoke`` call and
    exits this loop.

    Args:
        graph:         The compiled LangGraph ``CompiledStateGraph``.
        initial_input: Initial state dict for a fresh run, or ``None`` /
                       ``Command(resume=…)`` for resuming a checkpoint.
        config:        LangGraph run config (must include ``thread_id``).

    Returns:
        The final state dict.  Contains ``__interrupt__`` when the graph was
        paused by a pending pause signal; otherwise all nodes completed.
    """
    thread_id: str = config.get("configurable", {}).get("thread_id", "")
    state: Any = initial_input
    while True:
        result: dict = await graph.ainvoke(state, config)
        if "__interrupt__" not in result:
            return result
        # Check pause signal before auto-approving.
        if thread_id and await check_and_consume_pause_signal(thread_id):
            logger.info(
                "[graph_runner] pause_signal_consumed thread_id=%s interrupts=%s",
                thread_id,
                [i.value for i in result["__interrupt__"]],
            )
            return result  # caller handles the 'paused' transition
        # Auto-approve: immediately resume from the interrupt checkpoint.
        logger.debug(
            "[graph_runner] auto_approve interrupts=%s thread_id=%s",
            [i.value for i in result["__interrupt__"]],
            thread_id,
        )
        state = Command(resume=True)


async def run_graph_async(
    thread_id: str,
    query: str,
) -> None:
    """Run the LangGraph workflow for one query inside the FastAPI event loop.

    Called via ``asyncio.create_task()`` from the query ACK endpoint.  The
    graph routes internally based on ``query`` text:

    * ``"DO STREAMING PERFORMANCE TEST NOW"`` -> mock sub-graph
    * all other queries -> fin_analyst sub-graph

    After natural completion, the governance registry is swept for any streams
    that were not deregistered (e.g. due to a worker crash) and a
    ``stream_stopped`` event is published for each so the frontend receives
    a clean terminal event.

    Lifecycle:
        1. Transition phase to ``preparing``.
        2. Invoke the routed graph (outer -> agent sub-graph -> leaf node).
        3. Update ``UserQuery`` status and emit ``done`` when finished.
        4. Sweep governance registry for orphaned live streams.

    Args:
        thread_id: LangGraph UUID already persisted to the DB.
        query:     Raw query text, used for agent routing.
    """
    factory = _get_session_factory()
    try:
        # Transition phase to "preparing" as soon as the task is scheduled.
        # This signals to the frontend that the request is being processed.
        await set_query_phase(thread_id, "preparing")
        await emit_query_status(thread_id, "preparing")

        graph = get_compiled_graph()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        initial_state = {
            "thread_id": thread_id,
            "query": query,
        }
        final_state = await _invoke_with_auto_approve(graph, initial_state, config)

        # Paused: graph stopped at an interrupt checkpoint (pause signal was set).
        if "__interrupt__" in final_state:
            _running_tasks.pop(thread_id, None)
            running_tasks: list = []
            async with factory() as session:
                result = await session.execute(
                    update(UserQuery)
                    .where(
                        UserQuery.thread_id == thread_id,
                        UserQuery.status == "running",
                    )
                    .values(status="paused")
                    .returning(UserQuery.thread_id)
                )
                claimed = result.fetchone() is not None
                if claimed:
                    # Collect any running tasks so we can emit paused events
                    # before done.  For most graph flows the interrupt fires
                    # before any task runs (zero rows here), but we handle
                    # it generically for safety.
                    tasks_result = await session.execute(
                        select(AgentTask.task_id, AgentTask.task_name, AgentTask.node_name)
                        .where(
                            AgentTask.thread_id == thread_id,
                            AgentTask.status == "running",
                        )
                    )
                    running_tasks = tasks_result.fetchall()
                    await session.execute(
                        update(AgentTask)
                        .where(AgentTask.thread_id == thread_id, AgentTask.status == "running")
                        .values(status="paused")
                    )
                await session.commit()
            if claimed:
                await publish_governance_end(thread_id, reason="paused")
                _updated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                for row in running_tasks:
                    await publish_task_lifecycle(thread_id, {
                        "event": "cancelled",
                        "task_id": row.task_id,
                        "node_name": row.node_name,
                        "task_name": row.task_name,
                        "output": {},
                        "updated_at_ms": _updated_at_ms,
                    })
                await emit_done(thread_id, "paused", "Query paused at checkpoint")
            await cleanup_thread_session(thread_id)
            logger.info("[graph_runner] paused thread_id=%s", thread_id)
            return

        report = final_state.get("result") or "Stream completed"
        # Remove from running_tasks SYNCHRONOUSLY before any further awaits.
        # This closes the race window where the frontend safety-timeout fires
        # cancel_query after natural completion.
        _running_tasks.pop(thread_id, None)

        # Atomically claim ownership of the done transition.  Using WHERE
        # status='running' means only one writer (runner or cancel endpoint)
        # can commit and emit done -- whoever commits second touches 0 rows
        # and skips emit_done entirely, preventing duplicate done events.
        async with factory() as session:
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status == "running",
                )
                .values(
                    status="completed",
                    answer=report,
                    completed_at=datetime.utcnow(),
                )
                .returning(UserQuery.thread_id)
            )
            claimed = result.fetchone() is not None
            await session.commit()
        if claimed:
            await emit_done(thread_id, "completed", report)
            # Sweep for any streams that did not deregister (worker crash, etc.)
            # and emit stream_stopped so the frontend has a terminal event.
            await publish_governance_end(thread_id, reason="completed")

        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        # Cancel endpoint has already updated DB + emitted done; nothing to do.
        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] cancelled thread_id=%s", thread_id)
        raise

    except Exception as exc:
        logger.exception(
            "[graph_runner] error thread_id=%s: %s",
            thread_id,
            exc,
        )
        # Guard: only update if not already cancelled/completed by the cancel endpoint.
        try:
            async with factory() as session:
                uq = await session.scalar(
                    select(UserQuery).where(UserQuery.thread_id == thread_id)
                )
                if uq is not None and uq.status not in ("cancelled", "failed", "completed", "paused"):
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="failed", error=str(exc)[:1000])
                    )
                    await session.commit()
                    await emit_done(thread_id, "failed", str(exc), error_code=GRAPH_EXECUTION_FAILED)
                    # Sweep governance for any orphaned streams on error path.
                    await publish_governance_end(thread_id, reason="failed")
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] cleanup error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
        await cleanup_thread_session(thread_id)


async def run_resume_async(thread_id: str) -> None:
    """Resume a previously-cancelled LangGraph run from its last checkpoint.

    Passes ``input=None`` to :func:`_invoke_with_auto_approve` so LangGraph
    loads the most recent ``AsyncPostgresSaver`` checkpoint and re-runs the
    interrupted node from its beginning.  Any fresh ``interrupt()`` calls
    encountered during the resumed run are also auto-approved (or paused if
    a pause signal is set).  All lifecycle handling is identical to
    :func:`run_graph_async`.

    Checkpoint replay
    -----------------
    ``@task``-decorated subtask results that were already checkpointed before
    the cancel are replayed by LangGraph without re-executing the task body —
    only the node that was interrupted at its ``interrupt()`` boundary gets
    re-run from scratch.

    Args:
        thread_id: LangGraph UUID of the query to resume.
    """
    factory = _get_session_factory()
    try:
        await set_query_phase(thread_id, "preparing")
        await emit_query_status(thread_id, "preparing")

        graph = get_compiled_graph()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        # input=None tells LangGraph to resume from the last saved checkpoint.
        # _invoke_with_auto_approve also handles any fresh interrupt() calls
        # encountered during this resumed run.
        final_state = await _invoke_with_auto_approve(graph, None, config)

        # Paused during resumed run.
        if "__interrupt__" in final_state:
            _running_tasks.pop(thread_id, None)
            async with factory() as session:
                result = await session.execute(
                    update(UserQuery)
                    .where(
                        UserQuery.thread_id == thread_id,
                        UserQuery.status == "running",
                    )
                    .values(status="paused")
                    .returning(UserQuery.thread_id)
                )
                claimed = result.fetchone() is not None
                await session.commit()
            if claimed:
                await emit_done(thread_id, "paused", "Query paused at checkpoint")
                await publish_governance_end(thread_id, reason="paused")
            await cleanup_thread_session(thread_id)
            logger.info("[graph_runner] resumed_paused thread_id=%s", thread_id)
            return

        report = (final_state or {}).get("result") or "Stream completed"
        _running_tasks.pop(thread_id, None)

        async with factory() as session:
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status == "running",
                )
                .values(
                    status="completed",
                    answer=report,
                    completed_at=datetime.utcnow(),
                )
                .returning(UserQuery.thread_id)
            )
            claimed = result.fetchone() is not None
            await session.commit()
        if claimed:
            await emit_done(thread_id, "completed", report)
            await publish_governance_end(thread_id, reason="completed")

        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] resumed_completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] resumed_cancelled thread_id=%s", thread_id)
        raise

    except Exception as exc:
        logger.exception(
            "[graph_runner] resume_error thread_id=%s: %s",
            thread_id,
            exc,
        )
        try:
            async with factory() as session:
                uq = await session.scalar(
                    select(UserQuery).where(UserQuery.thread_id == thread_id)
                )
                if uq is not None and uq.status not in ("cancelled", "failed", "completed", "paused"):
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="failed", error=str(exc)[:1000])
                    )
                    await session.commit()
                    await emit_done(thread_id, "failed", str(exc), error_code=GRAPH_EXECUTION_FAILED)
                    await publish_governance_end(thread_id, reason="failed")
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] resume_cleanup_error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
        await cleanup_thread_session(thread_id)


async def run_resume_from_pause_async(thread_id: str) -> None:
    """Resume a paused LangGraph run from its interrupt checkpoint.

    Uses ``Command(resume=True)`` so LangGraph continues execution from the
    exact point where ``interrupt()`` was called — the interrupted node
    resumes rather than re-running from scratch.

    This is the correct resume path when the previous run was paused via
    ``POST /query/{thread_id}/pause``.  For cancelled/failed runs use
    :func:`run_resume_async` (``input=None``) instead.

    Args:
        thread_id: LangGraph UUID of the query to resume.
    """
    factory = _get_session_factory()
    try:
        await set_query_phase(thread_id, "preparing")
        await emit_query_status(thread_id, "preparing")

        graph = get_compiled_graph()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        # Clear any stale pause signal before resuming so the resumed run is not
        # immediately paused again by a leftover signal from the previous pause.
        await delete_pause_signal(thread_id)

        # Command(resume=True) continues from the interrupt checkpoint — the
        # node that was paused continues without re-executing from the start.
        final_state = await _invoke_with_auto_approve(graph, Command(resume=True), config)

        # Paused again during resumed run.
        if "__interrupt__" in final_state:
            _running_tasks.pop(thread_id, None)
            async with factory() as session:
                result = await session.execute(
                    update(UserQuery)
                    .where(
                        UserQuery.thread_id == thread_id,
                        UserQuery.status == "running",
                    )
                    .values(status="paused")
                    .returning(UserQuery.thread_id)
                )
                claimed = result.fetchone() is not None
                await session.commit()
            if claimed:
                await emit_done(thread_id, "paused", "Query paused at checkpoint")
                await publish_governance_end(thread_id, reason="paused")
            await cleanup_thread_session(thread_id)
            logger.info("[graph_runner] pause_resumed_paused thread_id=%s", thread_id)
            return

        report = (final_state or {}).get("result") or "Stream completed"
        _running_tasks.pop(thread_id, None)

        async with factory() as session:
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status == "running",
                )
                .values(
                    status="completed",
                    answer=report,
                    completed_at=datetime.utcnow(),
                )
                .returning(UserQuery.thread_id)
            )
            claimed = result.fetchone() is not None
            await session.commit()
        if claimed:
            await emit_done(thread_id, "completed", report)
            await publish_governance_end(thread_id, reason="completed")

        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] pause_resumed_completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] pause_resumed_cancelled thread_id=%s", thread_id)
        raise

    except Exception as exc:
        logger.exception(
            "[graph_runner] pause_resume_error thread_id=%s: %s",
            thread_id,
            exc,
        )
        try:
            async with factory() as session:
                uq = await session.scalar(
                    select(UserQuery).where(UserQuery.thread_id == thread_id)
                )
                if uq is not None and uq.status not in ("cancelled", "failed", "completed", "paused"):
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="failed", error=str(exc)[:1000])
                    )
                    await session.commit()
                    await emit_done(thread_id, "failed", str(exc), error_code=GRAPH_EXECUTION_FAILED)
                    await publish_governance_end(thread_id, reason="failed")
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] pause_resume_cleanup_error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
        await cleanup_thread_session(thread_id)


async def run_replay_from_node_async(thread_id: str, checkpoint_config: dict) -> None:
    """Replay a LangGraph run from a specific historical checkpoint.

    Invokes the compiled graph with ``input=None`` and a ``checkpoint_config``
    that points to the historical snapshot where the target node is in ``next``.
    LangGraph re-runs the target node and all subsequent nodes, overwriting
    future checkpoints in the same thread.  Nodes that completed before the
    replay point are replayed from their cached checkpoint outputs — not
    re-executed.

    All lifecycle handling (paused / completed / failed) mirrors
    :func:`run_graph_async`.

    Args:
        thread_id:         LangGraph UUID of the query being replayed.
        checkpoint_config: LangGraph config dict (with ``checkpoint_id``) from
                           the historical snapshot to resume from.
    """
    factory = _get_session_factory()
    try:
        await set_query_phase(thread_id, "preparing")
        await emit_query_status(thread_id, "preparing")

        graph = get_compiled_graph()
        # Build the outer-graph invocation config from checkpoint_config.
        # When the target node lives inside a subgraph (checkpoint_ns is
        # non-empty), the outer graph must be invoked at the ROOT namespace
        # with the parent's checkpoint_id from checkpoint_map[""].  The full
        # checkpoint_map is passed through so LangGraph can time-travel into
        # the correct subgraph checkpoint during replay.
        configurable = checkpoint_config.get("configurable", {})
        checkpoint_ns: str = configurable.get("checkpoint_ns", "")
        checkpoint_map: dict = configurable.get("checkpoint_map", {})

        if checkpoint_ns:
            # Subgraph checkpoint: root graph uses the ancestor checkpoint_id
            # stored in checkpoint_map[""] so it loads the correct outer state.
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint_map.get(""),
                    "checkpoint_map": checkpoint_map,
                }
            }
        else:
            # Root-level checkpoint: use as-is (checkpoint_id carried through).
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    **configurable,
                }
            }

        logger.debug(
            "[graph_runner] replay_config thread_id=%s checkpoint_ns=%r checkpoint_id=%s",
            thread_id,
            checkpoint_ns or "(root)",
            config["configurable"].get("checkpoint_id"),
        )

        # Clear any stale pause signal to avoid immediately re-pausing.
        await delete_pause_signal(thread_id)

        # input=None: LangGraph resumes from the checkpoint identified by
        # checkpoint_id in config, re-running nodes listed in snapshot.next.
        final_state = await _invoke_with_auto_approve(graph, None, config)

        # Paused during replay run.
        if "__interrupt__" in final_state:
            _running_tasks.pop(thread_id, None)
            running_tasks: list = []
            async with factory() as session:
                result = await session.execute(
                    update(UserQuery)
                    .where(
                        UserQuery.thread_id == thread_id,
                        UserQuery.status == "running",
                    )
                    .values(status="paused")
                    .returning(UserQuery.thread_id)
                )
                claimed = result.fetchone() is not None
                if claimed:
                    tasks_result = await session.execute(
                        select(AgentTask.task_id, AgentTask.task_name, AgentTask.node_name)
                        .where(
                            AgentTask.thread_id == thread_id,
                            AgentTask.status == "running",
                        )
                    )
                    running_tasks = tasks_result.fetchall()
                    await session.execute(
                        update(AgentTask)
                        .where(AgentTask.thread_id == thread_id, AgentTask.status == "running")
                        .values(status="paused")
                    )
                await session.commit()
            if claimed:
                await publish_governance_end(thread_id, reason="paused")
                _updated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                for row in running_tasks:
                    await publish_task_lifecycle(thread_id, {
                        "event": "cancelled",
                        "task_id": row.task_id,
                        "node_name": row.node_name,
                        "task_name": row.task_name,
                        "output": {},
                        "updated_at_ms": _updated_at_ms,
                    })
                await emit_done(thread_id, "paused", "Query paused at checkpoint")
            await cleanup_thread_session(thread_id)
            logger.info("[graph_runner] replay_paused thread_id=%s", thread_id)
            return

        report = final_state.get("result") or "Stream completed"
        _running_tasks.pop(thread_id, None)

        async with factory() as session:
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status == "running",
                )
                .values(
                    status="completed",
                    answer=report,
                    completed_at=datetime.utcnow(),
                )
                .returning(UserQuery.thread_id)
            )
            claimed = result.fetchone() is not None
            await session.commit()
        if claimed:
            await emit_done(thread_id, "completed", report)
            await publish_governance_end(thread_id, reason="completed")

        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] replay_completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] replay_cancelled thread_id=%s", thread_id)
        raise

    except Exception as exc:
        logger.exception(
            "[graph_runner] replay_error thread_id=%s: %s",
            thread_id,
            exc,
        )
        try:
            async with factory() as session:
                uq = await session.scalar(
                    select(UserQuery).where(UserQuery.thread_id == thread_id)
                )
                if uq is not None and uq.status not in ("cancelled", "failed", "completed", "paused"):
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="failed", error=str(exc)[:1000])
                    )
                    await session.commit()
                    await emit_done(thread_id, "failed", str(exc), error_code=GRAPH_EXECUTION_FAILED)
                    await publish_governance_end(thread_id, reason="failed")
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] replay_cleanup_error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
        await cleanup_thread_session(thread_id)


async def run_fork_from_checkpoint_async(thread_id: str, checkpoint_config: dict) -> None:
    """Run the forked LangGraph thread from its freshly-created checkpoint.

    Unlike :func:`run_replay_from_node_async`, the checkpoint was written to a
    *new* thread by ``graph.aupdate_state`` (in ``fork.py``).  We simply
    invoke the compiled graph from that checkpoint (``input=None`` causes
    LangGraph to load from the latest checkpoint on *thread_id*, which is
    the one just written by ``aupdate_state``).

    All lifecycle handling mirrors :func:`run_graph_async`.

    Args:
        thread_id:         New forked thread UUID (already has a ``user_queries``
                           row with status='running').
        checkpoint_config: Config returned by ``graph.aupdate_state`` — carries
                           the new ``checkpoint_id`` so LangGraph loads the
                           exact fork-point state.
    """
    factory = _get_session_factory()
    try:
        await set_query_phase(thread_id, "preparing")
        await emit_query_status(thread_id, "preparing")

        graph = get_compiled_graph()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                **checkpoint_config.get("configurable", {}),
            }
        }

        await delete_pause_signal(thread_id)

        # input=None: load from the checkpoint written by aupdate_state.
        final_state = await _invoke_with_auto_approve(graph, None, config)

        if "__interrupt__" in final_state:
            _running_tasks.pop(thread_id, None)
            async with factory() as session:
                result = await session.execute(
                    update(UserQuery)
                    .where(
                        UserQuery.thread_id == thread_id,
                        UserQuery.status == "running",
                    )
                    .values(status="paused")
                    .returning(UserQuery.thread_id)
                )
                claimed = result.fetchone() is not None
                await session.commit()
            if claimed:
                await emit_done(thread_id, "paused", "Forked query paused at checkpoint")
                await publish_governance_end(thread_id, reason="paused")
            await cleanup_thread_session(thread_id)
            logger.info("[graph_runner] fork_paused thread_id=%s", thread_id)
            return

        report = (final_state or {}).get("result") or "Fork completed"
        _running_tasks.pop(thread_id, None)

        async with factory() as session:
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status == "running",
                )
                .values(
                    status="completed",
                    answer=report,
                    completed_at=datetime.utcnow(),
                )
                .returning(UserQuery.thread_id)
            )
            claimed = result.fetchone() is not None
            await session.commit()
        if claimed:
            await emit_done(thread_id, "completed", report)
            await publish_governance_end(thread_id, reason="completed")

        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] fork_completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] fork_cancelled thread_id=%s", thread_id)
        raise

    except Exception as exc:
        logger.exception(
            "[graph_runner] fork_error thread_id=%s: %s",
            thread_id,
            exc,
        )
        try:
            async with factory() as session:
                uq = await session.scalar(
                    select(UserQuery).where(UserQuery.thread_id == thread_id)
                )
                if uq is not None and uq.status not in ("cancelled", "failed", "completed", "paused"):
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="failed", error=str(exc)[:1000])
                    )
                    await session.commit()
                    await emit_done(thread_id, "failed", str(exc), error_code=GRAPH_EXECUTION_FAILED)
                    await publish_governance_end(thread_id, reason="failed")
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] fork_cleanup_error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
        await cleanup_thread_session(thread_id)

