"""research_subgraph — parallel stats + news fetch followed by a merge node.

Hierarchy
---------
Thread
  └── research_subgraph  (Subgraph)
        ├── stats_node   (Workflow, parent=research_subgraph, parallel_group="fetch")
        │     └── read_stats   (@task → Celery completion worker)
        ├── news_node    (Workflow, parent=research_subgraph, parallel_group="fetch")
        │     └── read_news    (@task → Celery completion worker)
        └── merge_node   (Workflow, parent=research_subgraph)
              └── merge_results  (@task → Celery completion worker)
                    ↑
                    Task input is chained from read_stats + read_news outputs.

Execution pattern
-----------------
``orchestrate`` uses LangChain chain steps:

  Step 1 — PARALLEL (RunnableParallel):
    stats_node + news_node run concurrently.

  Step 2 — SEQUENTIAL (RunnableLambda, depends on both Step 1 results):
    merge_node runs with a ``MergeInput`` constructed from the two
    parallel outputs — this is intra-subgraph task output chaining.

Data flow
---------
``build_input`` reads query_node's output from ``fin_agents.node_executions``
via the PG replica (``read_node_output``).  ResearchSubgraphInput mirrors
QueryNodeOutput (intent, symbols, filters) — the regional analyze node is
the graph topology predecessor but the data dependency is on query_node.

Agent upgrade path
------------------
``orchestrate`` can be replaced with an LLM agent that uses read_stats,
read_news, and merge_results as tools.  The agent decides the execution
order; ``_StatsNode``, ``_NewsNode``, and ``_MergeNode`` remain unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import Runnable, RunnableLambda, RunnableParallel, RunnablePassthrough

from backend.db.postgres.types import NodeType
from backend.langgraph.nodes.base.node import BaseNode, ChildNode
from backend.langgraph.lifecycle import make_task_id, read_node_output
from backend.langgraph.nodes.base.models import NodeContext, TaskContext, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.research_subgraph.models import (
    ResearchSubgraphInput,
    ResearchSubgraphOutput,
)
from backend.langgraph.nodes.research_subgraph.tasks.models import (
    MergeInput,
    MergeOutput,
    ReadNewsInput,
    ReadNewsOutput,
    ReadStatsInput,
    ReadStatsOutput,
)
from backend.langgraph.nodes.research_subgraph.tasks import read_stats, read_news, merge_results
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Child nodes (private implementation details of the subgraph)
# ---------------------------------------------------------------------------


class _StatsNode(ChildNode[ReadStatsInput, ReadStatsOutput]):
    """Single-task child: fetches OHLCV stats for extracted symbols."""

    node_name = "stats_node"
    node_type = NodeType.WORKFLOW
    tasks: list[NodeTask] = [read_stats]

    def build_chain(self, ctx: NodeContext) -> Runnable[ReadStatsInput, dict[str, TaskOutput]]:
        return (
            self._task_as_runnable(read_stats, ctx)
            | RunnableLambda(lambda r: {read_stats.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> ReadStatsOutput:
        return results[read_stats.name].content

    def get_state_updates(self, output: ReadStatsOutput) -> dict[str, Any]:
        # Child nodes do not write directly to GraphState; the subgraph does.
        return {}


class _NewsNode(ChildNode[ReadNewsInput, ReadNewsOutput]):
    """Single-task child: fetches recent news articles for extracted symbols."""

    node_name = "news_node"
    node_type = NodeType.WORKFLOW
    tasks: list[NodeTask] = [read_news]

    def build_chain(self, ctx: NodeContext) -> Runnable[ReadNewsInput, dict[str, TaskOutput]]:
        return (
            self._task_as_runnable(read_news, ctx)
            | RunnableLambda(lambda r: {read_news.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> ReadNewsOutput:
        return results[read_news.name].content

    def get_state_updates(self, output: ReadNewsOutput) -> dict[str, Any]:
        return {}


class _MergeNode(ChildNode[MergeInput, MergeOutput]):
    """Single-task child: merges stats + news into a research summary.

    Input is constructed by the parent subgraph's build_chain from the
    chained outputs of _StatsNode and _NewsNode.
    """

    node_name = "merge_node"
    node_type = NodeType.WORKFLOW
    tasks: list[NodeTask] = [merge_results]

    def build_chain(self, ctx: NodeContext) -> Runnable[MergeInput, dict[str, TaskOutput]]:
        return (
            self._task_as_runnable(merge_results, ctx)
            | RunnableLambda(lambda r: {merge_results.name: r})
        )

    def build_output(self, results: dict[str, TaskOutput]) -> MergeOutput:
        return results[merge_results.name].content

    def get_state_updates(self, output: MergeOutput) -> dict[str, Any]:
        return {}


# ---------------------------------------------------------------------------
# Subgraph node
# ---------------------------------------------------------------------------


class ResearchSubgraph(BaseNode[ResearchSubgraphInput, ResearchSubgraphOutput]):
    """Fixed-flow research subgraph: parallel fetch then sequential merge.

    Child nodes are private instances; the subgraph's orchestrate wires
    them together with the correct input → output chaining.
    """

    node_name = "research_subgraph"
    node_type = NodeType.SUBGRAPH
    tasks: list[NodeTask] = [read_stats, read_news, merge_results]
    _prev_node_names: list[str] = ["apac_analyze_node", "emea_analyze_node", "amer_analyze_node"]

    _stats_node: _StatsNode = _StatsNode()
    _news_node: _NewsNode = _NewsNode()
    _merge_node: _MergeNode = _MergeNode()

    async def build_input(self, state: GraphState) -> ResearchSubgraphInput:
        """Read query_node output from the PG replica.

        ResearchSubgraphInput mirrors QueryNodeOutput (intent, symbols, filters).
        The graph topology predecessor is a regional analyze node, but the
        data dependency is on query_node's output.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        qa: dict = {}
        if query_node_id:
            qa = await read_node_output(query_node_id)
        return ResearchSubgraphInput.model_validate(qa)

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[ResearchSubgraphInput, dict[str, TaskOutput]]:
        """Chain: RunnableParallel fetch → RunnablePassthrough.assign merge → collect.

        Step 1 — PARALLEL (RunnableParallel):
            stats_node and news_node run concurrently; both receive the
            full ``ResearchSubgraphInput`` and return their typed outputs.

        Step 2 — PASS-THROUGH ASSIGN (RunnablePassthrough.assign):
            Extends the parallel output dict ``{"stats": ..., "news": ...}``
            with ``"merge"`` from merge_node, preserving the prior keys.

        Step 3 — COLLECT (RunnableLambda):
            Wraps all three outputs into the ``dict[str, TaskOutput]`` contract
            expected by ``build_output``.
        """
        async def _stats(inp: ResearchSubgraphInput) -> ReadStatsOutput:
            return await self._stats_node._run_as_child(
                parent_ctx=ctx,
                node_input=ReadStatsInput(symbols=inp.symbols or ["AAPL"], interval="1d"),
                parallel_group="fetch",
            )

        async def _news(inp: ResearchSubgraphInput) -> ReadNewsOutput:
            return await self._news_node._run_as_child(
                parent_ctx=ctx,
                node_input=ReadNewsInput(symbols=inp.symbols or ["AAPL"]),
                parallel_group="fetch",
            )

        async def _merge(fetched: dict[str, Any]) -> MergeOutput:
            return await self._merge_node._run_as_child(
                parent_ctx=ctx,
                node_input=MergeInput(
                    stats_data=fetched["stats"].model_dump(),
                    news_data=fetched["news"].model_dump(),
                ),
            )

        def _collect(result: dict[str, Any]) -> dict[str, TaskOutput]:
            return {
                read_stats.name: TaskOutput(
                    ctx=TaskContext(**ctx.model_dump(), task_id=make_task_id(), task_name=read_stats.name),
                    content=result["stats"],
                ),
                read_news.name: TaskOutput(
                    ctx=TaskContext(**ctx.model_dump(), task_id=make_task_id(), task_name=read_news.name),
                    content=result["news"],
                ),
                merge_results.name: TaskOutput(
                    ctx=TaskContext(**ctx.model_dump(), task_id=make_task_id(), task_name=merge_results.name),
                    content=result["merge"],
                ),
            }

        fetch_step = RunnableParallel(
            stats=RunnableLambda(_stats),
            news=RunnableLambda(_news),
        )
        merge_step = RunnablePassthrough.assign(merge=RunnableLambda(_merge))
        collect_step = RunnableLambda(_collect)

        return fetch_step | merge_step | collect_step

    def build_output(self, results: dict[str, TaskOutput]) -> ResearchSubgraphOutput:
        """Bundle all child results into a single subgraph output."""
        return ResearchSubgraphOutput(
            stats_data=results[read_stats.name].content.model_dump(),
            news_data=results[read_news.name].content.model_dump(),
            merged_research=results[merge_results.name].content.model_dump(),
        )

    def get_state_updates(self, output: ResearchSubgraphOutput) -> dict[str, Any]:
        """No state updates — output stored in node_executions via lifecycle."""
        return {}


# Module-level callable registered with LangGraph StateGraph.
research_subgraph = ResearchSubgraph()
