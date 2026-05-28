"""BaseNode and ChildNode — the agent-ready node template.

Design: node as agent contract
-------------------------------
Every node exposes these methods that together define its contract:

    build_input(state)      — reads typed input from predecessor outputs via DB
    build_chain(ctx)        — composes task steps into a Runnable chain (agent loop later)
    build_output(results)   — selects / composes from task outputs for the node output
    get_state_updates(out)  — maps node output to GraphState key updates (usually {})

The ``build_chain`` method is the seam for the agent upgrade:

    Chain flow (current):
        Compose ``_task_as_runnable`` steps using LangChain operators::

            Sequential:   step_a | step_b | collect
            Parallel:     RunnableParallel(a=step_a, b=step_b) | merge | collect
            Pass-through: RunnablePassthrough.assign(key=step) to extend a
                          dict while preserving prior keys.

    Agent mode (future override):
        Return a ``RunnableLambda`` wrapping a LangChain ReAct agent that
        uses ``self.tasks`` as tools.  The ``dict[str, TaskOutput]``
        output contract for ``build_output`` is unchanged.

Lifecycle
---------
``__call__``              — top-level LangGraph entrypoint (enters + orchestrates + exits)
``_run_as_child``         — called by a parent subgraph; same lifecycle but with
                            ``parent_node_id`` and optional ``parallel_group``.
``run_task``              — stamps a fresh TaskContext and invokes the @task fn.
``_task_as_runnable``     — wraps a NodeTask as a ``RunnableLambda`` chain step.

Fork versioning
---------------
``__call__`` reads ``state.get("fork_generation", 1)`` to determine the
version for this branch.  The node_id is UUID5(thread_id, node_name, version)
ensuring forked nodes are distinct from original-run nodes.

Node output data flow
---------------------
Node inputs/outputs are NOT passed through GraphState.  Instead:
- Inputs are written to ``fin_agents.node_executions`` via ``upsert_node``.
- Outputs are written to ``fin_agents.node_executions`` via ``complete_node``.
- Downstream nodes read predecessor output via ``read_node_output(node_id)``
  (which queries the PG replica).
This keeps checkpoint blobs small and reduces primary DB load.

Implementation is split across mixins in ``node_utils``:
- TypeValidationMixin  : Generic[I, O] resolution and model validation.
- StateUtilsMixin      : GraphState inspection and NodeRecord construction.
- TaskRunnerMixin      : Task execution and Runnable wrapping.
- CancelHandlerMixin   : Node/thread cancellation and cascade logic.
- ChildRunnerMixin     : Running a node as a subgraph child.
- EntrypointMixin      : LangGraph ``__call__`` entrypoint implementation.
- AgentStepMixin       : Generic named-step loop for NodeType.AGENT nodes.

Agent step loop (``AgentStepMixin``)
------------------------------------
Nodes with ``node_type == NodeType.AGENT`` may either:

1. Set ``agent_steps: ClassVar[dict[str, Callable]]`` and ``agent_step_order: ClassVar[list[str]]``
   to use the generic loop in ``AgentStepMixin.build_agent``.
2. Override ``build_agent(ctx, node_input)`` directly for custom behaviour.

A missing both will raise ``TypeError`` at class-definition time via
``__init_subclass__``.  Abstract intermediate classes are exempt (no
``node_name`` key in their ``__dict__``).

Hook methods for the generic loop (implement in the concrete node):
- ``_create_agent_global_state(node_input)``
- ``_create_agent_step_state(iteration, global_state, input_overrides)``
- ``_create_step_context(ctx, global_state, step_state, results, node_input)``
- ``_build_orchestration_input(global_state, step_state, failed_step, results, iteration)``
- ``_build_final_output(global_state, results, node_input)``
- ``_post_iteration_hook(ctx, global_state, step_state, results)``  (optional; no-op default)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from langchain_core.runnables import Runnable

from backend.db.postgres.types import NodeType
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.node_utils import (
    AgentStepMixin,
    CancelHandlerMixin,
    ChildRunnerMixin,
    EntrypointMixin,
    StateUtilsMixin,
    TaskRunnerMixin,
    TypeValidationMixin,
)
from backend.langgraph.models.task import NodeTask
from backend.langgraph.state import GraphState

I = TypeVar("I")
O = TypeVar("O")


class BaseNode(
    TypeValidationMixin,
    StateUtilsMixin,
    TaskRunnerMixin,
    CancelHandlerMixin,
    ChildRunnerMixin,
    EntrypointMixin,
    AgentStepMixin,
    ABC,
    Generic[I, O],
):
    """Template for all LangGraph nodes — fixed-flow now, agent-upgradeable later.

    Class variables:
        node_name: Registered node name; used in DB rows and SSE events.
        node_type: ``NodeType.WORKFLOW`` or ``NodeType.SUBGRAPH``.
        display_name: Human-readable label for the UI (defaults to node_name).
        category: UI grouping category (e.g. ``"Query"``, ``"Analysis"``).
        config_fields: Per-field metadata describing user-configurable options.
            Each entry is a dict matching the ``NodeConfigField`` shape used by
            the ``GET /api/v1/graph/node-metas`` response.
        tasks: Ordered list of ``NodeTask`` instances.  In agent mode this
            becomes the tool registry surfaced to the LLM.
        _prev_node_names: List of predecessor node names in the graph.
            Used to resolve prev_node_ids from the current state.
        parallel_group: Optional shared label that groups all nodes executing
            concurrently within the same parent scope.  Set this on every
            top-level node that participates in a fan-out / fan-in.
        parallel_branch: Optional branch identity within the parallel_group.
            Defaults to ``node_name`` when ``parallel_group`` is set.
            For multi-node sequential chains within a branch, set this to the
            same value on every node in the chain.
    """

    node_name: ClassVar[str]
    node_type: ClassVar[NodeType]
    display_name: ClassVar[str] = ""
    category: ClassVar[str] = "Workflow"
    config_fields: ClassVar[list[dict]] = []
    view_type: ClassVar[str] = "Json"
    # Per-field rendering schema for Mirror/Hybrid nodes.
    # Mirror: {"task_id": "<task_id>"}
    # Hybrid: {"<field>": "<view_type>" | {"type": "Mirror", "task_id": "<task_id>"}}
    view_schema: ClassVar[dict[str, Any]] = {}
    # Ordered list of stats_view_types names for Stats-view nodes.
    stats_views: ClassVar[list[str]] = []
    tasks: ClassVar[list[NodeTask]]
    _prev_node_names: ClassVar[list[str]] = []
    parallel_group: ClassVar[str | None] = None
    parallel_branch: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce that concrete AGENT nodes provide a step registry or build_agent override.

        Skips enforcement for abstract or intermediate classes (no ``node_name``
        key in their own ``__dict__``).

        Raises:
            TypeError: When a concrete AGENT node has neither ``agent_steps``
                ClassVar nor a ``build_agent`` override below ``BaseNode``.
        """
        super().__init_subclass__(**kwargs)
        if getattr(cls, "node_type", None) is None:
            return
        from backend.db.postgres.types import NodeType as _NT  # noqa: PLC0415
        if getattr(cls, "node_type", None) != _NT.AGENT:
            return
        if "node_name" not in cls.__dict__:
            return  # abstract / intermediate class
        if cls.agent_steps is not None:
            if cls.agent_global_state_class is None:
                raise TypeError(
                    f"{cls.__name__}: AGENT node with agent_steps must also set "
                    "agent_global_state_class ClassVar."
                )
            return  # step registry + global state class present — OK
        base_node_idx = next(
            (i for i, c in enumerate(cls.__mro__) if c.__name__ == "BaseNode"),
            len(cls.__mro__),
        )
        for c in cls.__mro__[:base_node_idx]:
            if "build_agent" in c.__dict__:
                return  # overridden below BaseNode — OK
        raise TypeError(
            f"{cls.__name__}: NodeType.AGENT must set agent_steps ClassVar "
            "or override build_agent()."
        )

    @abstractmethod
    async def build_input(self, state: GraphState) -> I:
        """Construct typed node input from predecessor outputs in the DB.

        Reads predecessor node output via ``read_node_output(node_id)``
        (which queries the PG replica) rather than from GraphState blobs.
        Returns a fully-typed input model.
        """

    def build_chain(self, ctx: NodeContext) -> Runnable[I, dict[str, TaskOutput]]:
        """Compose the node's task steps into a LangChain ``Runnable`` chain.

        Override in workflow nodes.  Agent nodes (``node_type == NodeType.AGENT``)
        use ``build_agent`` instead and do not need to implement this method.

        Raises:
            NotImplementedError: Default; workflow subclasses must override.
        """
        raise NotImplementedError(
            f"{self.node_name!r} does not implement build_chain()."
        )

    # build_agent is provided by AgentStepMixin (delegates to _run_agent_step_loop
    # when agent_steps / agent_step_order are set, or raises NotImplementedError).

    async def orchestrate(
        self, ctx: NodeContext, node_input: I
    ) -> dict[str, TaskOutput]:
        """Execute the node's chain or agent and return keyed task results.

        For ``AGENT`` nodes, skill files from the node's ``skills/`` directory
        are loaded into ``ctx.metadata["node_skills"]`` before ``build_agent``
        is called, so every agent implementation can inject them as system
        prompts without boilerplate.  A sandbox session is also started before
        ``build_agent`` and unconditionally cleaned up afterwards so every task
        inside the agent shares one persistent working directory for the
        duration of this node execution.
        """
        if self.node_type == NodeType.AGENT:
            import inspect  # noqa: PLC0415
            import pathlib  # noqa: PLC0415

            node_file = pathlib.Path(inspect.getfile(type(self)))
            skills_dir = node_file.parent / "skills"
            if skills_dir.is_dir():
                skill_texts = [
                    p.read_text(encoding="utf-8")
                    for p in sorted(skills_dir.glob("*.md"))
                ]
                if skill_texts:
                    ctx.metadata["node_skills"] = skill_texts

            from backend.sandbox.session import end_node_session, start_node_session  # noqa: PLC0415

            await start_node_session(ctx.node_id, ctx.thread_id)
            try:
                return await self.build_agent(ctx, node_input)
            finally:
                await end_node_session(ctx.node_id, ctx.thread_id)
        return await self.build_chain(ctx).ainvoke(node_input)

    def update_agent_memory(self, ctx: NodeContext, entries: list[dict]) -> None:
        """Append *entries* to the in-flight agent memory for this execution.

        Memory is stored in ``ctx.metadata["agent_memory"]`` so it is
        scoped to the current node execution (``NodeContext`` is created fresh
        per ``__call__``).  Concurrent executions across threads each hold
        their own ``NodeContext``, so there is no shared-state risk.

        Args:
            ctx:     The ``NodeContext`` for the current execution.
            entries: New memory entries to append.  Schema is defined by the
                     caller; ``prepare_peers`` uses
                     ``{"symbol": str, "corr": float, "status": str}``.
        """
        ctx.metadata.setdefault("agent_memory", []).extend(entries)

    @abstractmethod
    def build_output(self, results: dict[str, TaskOutput]) -> O:
        """Select and compose node output from task results."""

    @abstractmethod
    def get_state_updates(self, output: O) -> dict[str, Any]:
        """Map node output to GraphState key → value updates.

        Most nodes return ``{}`` since data flows via DB, not state.
        ``conclusion_node`` returns ``{"conclusion": output.answer}`` so
        ``executor.py`` can read it from ``final_state``.
        """


class ChildNode(BaseNode[I, O], ABC):
    """Base for nodes used exclusively as children within a subgraph.

    Subclasses must implement ``orchestrate``, ``build_output``, and
    ``get_state_updates``.  They must NOT be registered in the top-level
    LangGraph graph — use ``_run_as_child()`` from the parent instead.
    """

    async def build_input(self, state: GraphState) -> I:
        """Not applicable for child nodes."""
        raise NotImplementedError(
            f"{self.node_name!r} is a child-only node. "
            "Call _run_as_child() from the parent subgraph, not __call__()."
        )


__all__ = ["BaseNode", "ChildNode"]
