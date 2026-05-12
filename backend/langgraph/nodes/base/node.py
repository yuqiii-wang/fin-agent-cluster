"""BaseNode and ChildNode — the agent-ready node template.

Design: node as agent contract
-------------------------------
Every node exposes these methods that together define its contract:

    build_input(state)      — reads typed input from the previous node's state slice
    build_chain(ctx)        — composes task steps into a Runnable chain (agent loop later)
    build_output(results)   — selects / composes from task outputs for the node output
    get_state_updates(out)  — maps node output to GraphState key updates

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
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.langgraph.state import GraphState
from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import (
    complete_node,
    make_node_id,
    make_task_id,
    upsert_node,
)
from backend.langgraph.nodes.base.models import NodeContext, TaskContext, TaskInput, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask

I = TypeVar("I")
O = TypeVar("O")

logger = logging.getLogger(__name__)


class BaseNode(ABC, Generic[I, O]):
    """Template for all LangGraph nodes — fixed-flow now, agent-upgradeable later.

    Class variables:
        node_name: Registered node name; used in DB rows and SSE events.
        node_type: ``NodeType.WORKFLOW`` or ``NodeType.SUBGRAPH``.
        tasks: Ordered list of ``NodeTask`` instances.  In agent mode this
            becomes the tool registry surfaced to the LLM.
    """

    node_name: ClassVar[str]
    node_type: ClassVar[NodeType]
    tasks: ClassVar[list[NodeTask]]

    @abstractmethod
    def build_input(self, state: GraphState) -> I:
        """Construct typed node input from GraphState.

        Reads the previous node's output slice(s) from *state* and returns
        a fully-typed input model.  This is the explicit inter-node data
        contract: the consuming node declares exactly which state keys it
        needs and how they map to its input type.
        """

    @abstractmethod
    def build_chain(self, ctx: NodeContext) -> Runnable[I, dict[str, TaskOutput]]:
        """Compose the node's task steps into a LangChain ``Runnable`` chain.

        Build and return a ``Runnable`` that accepts the node's typed input
        (``I``) and produces ``dict[str, TaskOutput]`` keyed by task name.

        Chain patterns::

            # Sequential
            step_a | step_b | collect

            # Parallel then sequential
            RunnableParallel(a=step_a, b=step_b)
            | RunnablePassthrough.assign(merge=merge_step)
            | collect_step

        Each task step is obtained via ``self._task_as_runnable(task, ctx)``.

        Agent mode (future override):
            Return a ``RunnableLambda`` wrapping a LangChain ReAct agent that
            uses ``self.tasks`` as tools.  The ``dict[str, TaskOutput]``
            output contract is unchanged.
        """

    async def orchestrate(
        self, ctx: NodeContext, node_input: I
    ) -> dict[str, TaskOutput]:
        """Execute the node's chain and return keyed task results.

        Calls ``build_chain(ctx).ainvoke(node_input)``.  Override
        ``build_chain`` — not this method.
        """
        return await self.build_chain(ctx).ainvoke(node_input)

    @abstractmethod
    def build_output(self, results: dict[str, TaskOutput]) -> O:
        """Select and compose node output from task results.

        Receives the full ``results`` dict from ``orchestrate``.  Returns a
        typed node output model carrying only the fields this node exposes
        to downstream nodes via ``get_state_updates``.
        """

    @abstractmethod
    def get_state_updates(self, output: O) -> dict[str, Any]:
        """Map node output to GraphState key → value updates."""

    async def run_task(
        self,
        node_task: NodeTask,
        ctx: NodeContext,
        content: Any,
    ) -> TaskOutput:
        """Build TaskInput envelope and invoke the @task fn.

        Stamps a fresh ``task_id`` so every invocation is independently
        tracked in ``fin_agents.tasks``.

        Args:
            node_task: The ``NodeTask`` whose ``task_fn`` to invoke.
            ctx: Current node context (thread_id, node_id, node_name).
            content: Typed biz input; must match ``node_task.input_type``.

        Returns:
            ``TaskOutput`` with the same ``TaskContext`` and typed content.
        """
        task_ctx = TaskContext(
            **ctx.model_dump(),
            task_id=make_task_id(),
            task_name=node_task.name,
        )
        return await node_task.task_fn(TaskInput(ctx=task_ctx, content=content))

    def _task_as_runnable(self, task: NodeTask, ctx: NodeContext) -> RunnableLambda:
        """Wrap a NodeTask as a LangChain ``RunnableLambda`` chain step.

        Each call produces a fresh ``RunnableLambda`` whose ``ainvoke``
        delegates to ``run_task``.  Use this inside ``orchestrate`` to
        compose tasks into a LangChain chain.

        Args:
            task: The ``NodeTask`` to wrap.
            ctx:  Current ``NodeContext`` — bound at construction time.

        Returns:
            A ``RunnableLambda`` that accepts the task's input content and
            returns a ``TaskOutput``.
        """
        async def _step(content: Any) -> TaskOutput:
            return await self.run_task(task, ctx, content)

        return RunnableLambda(_step)

    async def _run_as_child(
        self,
        parent_ctx: NodeContext,
        node_input: I,
        parallel_group: str | None = None,
    ) -> O:
        """Run this node as a child within a parent subgraph.

        Handles the full upsert → orchestrate → complete lifecycle with
        ``parent_node_id`` set to ``parent_ctx.node_id``.  Called by the
        subgraph's ``orchestrate()`` instead of ``__call__``.

        Args:
            parent_ctx: The parent subgraph's NodeContext.
            node_input: Typed input — constructed by the parent, not from state.
            parallel_group: Optional label grouping sibling parallel nodes.

        Returns:
            Typed node output (``O``).
        """
        thread_id = parent_ctx.thread_id
        node_id = make_node_id(thread_id, self.node_name)
        ctx = NodeContext(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
        )
        await upsert_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            node_type=self.node_type,
            parent_node_id=parent_ctx.node_id,
            input_data=node_input.model_dump(),
            parallel_group=parallel_group,
        )
        try:
            results = await self.orchestrate(ctx, node_input)
        except Exception as exc:
            await complete_node(
                thread_id=thread_id,
                node_id=node_id,
                node_name=self.node_name,
                failed=True,
                error=str(exc),
            )
            raise
        node_output = self.build_output(results)
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            output_data=node_output.model_dump(),
        )
        return node_output

    async def __call__(self, state: GraphState) -> GraphState:
        """LangGraph entrypoint.

        Wires: build_input(state) → upsert_node → orchestrate(ctx, inp)
               → build_output(results) → complete_node → state updates.
        """
        thread_id: str = state["thread_id"]
        node_id = make_node_id(thread_id, self.node_name)
        node_input = self.build_input(state)
        ctx = NodeContext(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
        )
        await upsert_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            node_type=self.node_type,
            input_data=node_input.model_dump(),
        )
        try:
            results = await self.orchestrate(ctx, node_input)
        except Exception as exc:
            await complete_node(
                thread_id=thread_id,
                node_id=node_id,
                node_name=self.node_name,
                failed=True,
                error=str(exc),
            )
            raise
        node_output = self.build_output(results)
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=self.node_name,
            output_data=node_output.model_dump(),
        )
        return {**state, **self.get_state_updates(node_output)}


class ChildNode(BaseNode[I, O], ABC):
    """Base for nodes used exclusively as children within a subgraph.

    Subclasses must implement ``orchestrate``, ``build_output``, and
    ``get_state_updates``.  They must NOT be registered in the top-level
    LangGraph graph — use ``_run_as_child()`` from the parent instead.
    """

    def build_input(self, state: GraphState) -> I:
        """Not applicable for child nodes."""
        raise NotImplementedError(
            f"{self.node_name!r} is a child-only node. "
            "Call _run_as_child() from the parent subgraph, not __call__()."
        )


__all__ = ["BaseNode", "ChildNode"]
