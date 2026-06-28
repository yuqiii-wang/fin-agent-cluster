"""BaseNode and ChildNode -- the workflow node template.

Design: node contract
---------------------
Every node exposes these methods that together define its contract:

    build_input(state)      -- reads typed input from predecessor outputs via DB
    build_chain(ctx)        -- composes task steps into a Runnable chain
    build_output(results)   -- selects / composes from task outputs for the node output
    get_state_updates(out)  -- maps node output to GraphState key updates (usually {})

Chain flow
----------
Compose ``_task_as_runnable`` steps using LangChain operators::

    Sequential:   step_a | step_b | collect
    Parallel:     RunnableParallel(a=step_a, b=step_b) | merge | collect
    Pass-through: RunnablePassthrough.assign(key=step) to extend a
                  dict while preserving prior keys.

Lifecycle
---------
``__call__``              -- top-level LangGraph entrypoint (enters + orchestrates + exits)
``_run_as_child``         -- called by a parent subgraph; same lifecycle but with
                            ``parent_node_id`` and optional ``parallel_group``.
``run_task``              -- stamps a fresh TaskContext and invokes the @task fn.
``_task_as_runnable``     -- wraps a NodeTask as a ``RunnableLambda`` chain step.

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
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from langchain_core.runnables import Runnable

from backend.db.postgres.types import NodeType
from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.models.node_utils import (
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
    ABC,
    Generic[I, O],
):
    """Template for all LangGraph workflow nodes.

    Class variables:
        node_name: Registered node name; used in DB rows and SSE events.
        node_type: ``NodeType.WORKFLOW`` or ``NodeType.SUBGRAPH``.
        display_name: Human-readable label for the UI (defaults to node_name).
        category: UI grouping category (e.g. ``"Query"``, ``"Analysis"``).
        config_fields: Per-field metadata describing user-configurable options.
            Each entry is a dict matching the ``NodeConfigField`` shape used by
            the ``GET /api/v1/graph/node-metas`` response.
        tasks: Ordered list of ``NodeTask`` instances.
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

    @abstractmethod
    async def build_input(self, state: GraphState) -> I:
        """Construct typed node input from predecessor outputs in the DB.

        Reads predecessor node output via ``read_node_output(node_id)``
        (which queries the PG replica) rather than from GraphState blobs.
        Returns a fully-typed input model.
        """

    def build_chain(self, ctx: NodeContext) -> Runnable[I, dict[str, TaskOutput]]:
        """Compose the node's task steps into a LangChain ``Runnable`` chain.

        Raises:
            NotImplementedError: Default; workflow subclasses must override.
        """
        raise NotImplementedError(
            f"{self.node_name!r} does not implement build_chain()."
        )

    async def orchestrate(
        self, ctx: NodeContext, node_input: I
    ) -> dict[str, TaskOutput]:
        """Execute the node's chain and return keyed task results."""
        return await self.build_chain(ctx).ainvoke(node_input)

    @abstractmethod
    def build_output(self, results: dict[str, TaskOutput]) -> O:
        """Select and compose node output from task results."""

    @abstractmethod
    def get_state_updates(self, output: O) -> dict[str, Any]:
        """Map node output to GraphState key -> value updates.

        Most nodes return ``{}`` since data flows via DB, not state.
        ``conclusion_node`` returns ``{"conclusion": output.answer}`` so
        ``executor.py`` can read it from ``final_state``.
        """


class ChildNode(BaseNode[I, O], ABC):
    """Base for nodes used exclusively as children within a subgraph.

    Subclasses must implement ``orchestrate``, ``build_output``, and
    ``get_state_updates``.  They must NOT be registered in the top-level
    LangGraph graph -- use ``_run_as_child()`` from the parent instead.
    """

    async def build_input(self, state: GraphState) -> I:
        """Not applicable for child nodes."""
        raise NotImplementedError(
            f"{self.node_name!r} is a child-only node. "
            "Call _run_as_child() from the parent subgraph, not __call__()."
        )


__all__ = ["BaseNode", "ChildNode"]
