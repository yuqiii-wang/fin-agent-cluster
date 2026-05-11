"""research_subgraph — parallel stats + news fetch followed by a merge node.

Hierarchy
---------
Thread
  └── research_subgraph  (Subgraph node)
        ├── stats_node  (Typical, parent=research_subgraph)
        │     └── read_stats  (@task → Celery completion worker)
        ├── news_node   (Typical, parent=research_subgraph)
        │     └── read_news   (@task → Celery completion worker)
        └── merge_node  (Typical, parent=research_subgraph)
              └── merge_results  (@task → Celery completion worker)

stats_node and news_node run **concurrently** (asyncio.gather).
merge_node runs after both finish.

SSE events emitted
------------------
* task_status: running/completed for each @task
* node_status (auto) for each child node when all its tasks finish
* node_status (auto) for the subgraph node when all child nodes finish
  (node completion is triggered after merge_node completes).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.func import task

from backend.langgraph.state import GraphState
from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import (
    complete_node,
    complete_task,
    create_task,
    make_node_id,
    make_task_id,
    upsert_node,
)
from backend.langgraph.models import (
    AnalyzeQueryOutput,
    BaseNodeInput,
    BaseNodeOutput,
    BaseTaskInput,
    BaseTaskOutput,
    MergeResultsInput,
    MergeResultsOutput,
    ReadNewsInput,
    ReadNewsOutput,
    ReadStatsInput,
    ReadStatsOutput,
)
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_SUBGRAPH_NAME = "research_subgraph"
_STATS_NODE = "stats_node"
_NEWS_NODE = "news_node"
_MERGE_NODE = "merge_node"


# ---------------------------------------------------------------------------
# @task: read_stats
# ---------------------------------------------------------------------------


@task
async def read_stats(
    task_input: BaseTaskInput[ReadStatsInput],
) -> BaseTaskOutput[ReadStatsOutput]:
    """Fetch market statistics for symbols extracted by query_node.

    Args:
        task_input: Typed envelope carrying thread/node/task identity and
            the :class:`ReadStatsInput` content.

    Returns:
        :class:`BaseTaskOutput` wrapping the :class:`ReadStatsOutput`.
    """
    thread_id = task_input.thread_id
    node_id = task_input.node_id
    task_id = task_input.task_id
    payload = task_input.content.model_dump()

    await create_task(thread_id, node_id, _STATS_NODE, task_id, "read_stats", payload)
    try:
        result = await delegate_completion(
            thread_id, task_id, node_id, _STATS_NODE, "read_stats", payload
        )
    except Exception as exc:
        await complete_task(
            thread_id, node_id, _STATS_NODE, task_id, "read_stats",
            failed=True, error=str(exc),
        )
        raise
    output_content = ReadStatsOutput.model_validate(result)
    return BaseTaskOutput[ReadStatsOutput](
        thread_id=thread_id,
        node_id=node_id,
        task_id=task_id,
        task_name="read_stats",
        content=output_content,
    )


# ---------------------------------------------------------------------------
# @task: read_news
# ---------------------------------------------------------------------------


@task
async def read_news(
    task_input: BaseTaskInput[ReadNewsInput],
) -> BaseTaskOutput[ReadNewsOutput]:
    """Fetch recent news articles for symbols extracted by query_node.

    Args:
        task_input: Typed envelope carrying thread/node/task identity and
            the :class:`ReadNewsInput` content.

    Returns:
        :class:`BaseTaskOutput` wrapping the :class:`ReadNewsOutput`.
    """
    thread_id = task_input.thread_id
    node_id = task_input.node_id
    task_id = task_input.task_id
    payload = task_input.content.model_dump()

    await create_task(thread_id, node_id, _NEWS_NODE, task_id, "read_news", payload)
    try:
        result = await delegate_completion(
            thread_id, task_id, node_id, _NEWS_NODE, "read_news", payload
        )
    except Exception as exc:
        await complete_task(
            thread_id, node_id, _NEWS_NODE, task_id, "read_news",
            failed=True, error=str(exc),
        )
        raise
    output_content = ReadNewsOutput.model_validate(result)
    return BaseTaskOutput[ReadNewsOutput](
        thread_id=thread_id,
        node_id=node_id,
        task_id=task_id,
        task_name="read_news",
        content=output_content,
    )


# ---------------------------------------------------------------------------
# @task: merge_results
# ---------------------------------------------------------------------------


@task
async def merge_results(
    task_input: BaseTaskInput[MergeResultsInput],
) -> BaseTaskOutput[MergeResultsOutput]:
    """Combine stats and news data into a unified research summary.

    Args:
        task_input: Typed envelope carrying thread/node/task identity and
            the :class:`MergeResultsInput` content.

    Returns:
        :class:`BaseTaskOutput` wrapping the :class:`MergeResultsOutput`.
    """
    thread_id = task_input.thread_id
    node_id = task_input.node_id
    task_id = task_input.task_id
    payload = task_input.content.model_dump()

    await create_task(thread_id, node_id, _MERGE_NODE, task_id, "merge_results", payload)
    try:
        result = await delegate_completion(
            thread_id, task_id, node_id, _MERGE_NODE, "merge_results", payload
        )
    except Exception as exc:
        await complete_task(
            thread_id, node_id, _MERGE_NODE, task_id, "merge_results",
            failed=True, error=str(exc),
        )
        raise
    output_content = MergeResultsOutput.model_validate(result)
    return BaseTaskOutput[MergeResultsOutput](
        thread_id=thread_id,
        node_id=node_id,
        task_id=task_id,
        task_name="merge_results",
        content=output_content,
    )


# ---------------------------------------------------------------------------
# Individual child-node runners (called inside the subgraph function)
# ---------------------------------------------------------------------------


async def _run_stats_node(
    state: GraphState,
    subgraph_node_id: str,
    analysis: AnalyzeQueryOutput,
) -> ReadStatsOutput:
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _STATS_NODE)

    stats_input = ReadStatsInput(symbols=analysis.symbols, interval="1d")
    node_input = BaseNodeInput[ReadStatsInput](
        thread_id=thread_id,
        node_id=node_id,
        node_name=_STATS_NODE,
        content=stats_input,
    )

    await upsert_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_STATS_NODE,
        node_type=NodeType.TYPICAL,
        parent_node_id=subgraph_node_id,
        input_data=node_input.content.model_dump(),
        parallel_group="fetch",
    )

    task_input = BaseTaskInput[ReadStatsInput](
        thread_id=thread_id,
        node_id=node_id,
        task_id=make_task_id(),
        task_name="read_stats",
        content=stats_input,
    )

    try:
        task_output: BaseTaskOutput[ReadStatsOutput] = await read_stats(task_input)
    except Exception as exc:
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=_STATS_NODE,
            failed=True,
            error=str(exc),
        )
        raise

    node_output = BaseNodeOutput[ReadStatsOutput](
        thread_id=thread_id,
        node_id=node_id,
        node_name=_STATS_NODE,
        content=task_output.content,
    )
    await complete_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_STATS_NODE,
        output_data=node_output.content.model_dump(),
    )
    return node_output.content


async def _run_news_node(
    state: GraphState,
    subgraph_node_id: str,
    analysis: AnalyzeQueryOutput,
) -> ReadNewsOutput:
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _NEWS_NODE)

    news_input = ReadNewsInput(symbols=analysis.symbols)
    node_input = BaseNodeInput[ReadNewsInput](
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NEWS_NODE,
        content=news_input,
    )

    await upsert_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NEWS_NODE,
        node_type=NodeType.TYPICAL,
        parent_node_id=subgraph_node_id,
        input_data=node_input.content.model_dump(),
        parallel_group="fetch",
    )

    task_input = BaseTaskInput[ReadNewsInput](
        thread_id=thread_id,
        node_id=node_id,
        task_id=make_task_id(),
        task_name="read_news",
        content=news_input,
    )

    try:
        task_output: BaseTaskOutput[ReadNewsOutput] = await read_news(task_input)
    except Exception as exc:
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=_NEWS_NODE,
            failed=True,
            error=str(exc),
        )
        raise

    node_output = BaseNodeOutput[ReadNewsOutput](
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NEWS_NODE,
        content=task_output.content,
    )
    await complete_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NEWS_NODE,
        output_data=node_output.content.model_dump(),
    )
    return node_output.content


# ---------------------------------------------------------------------------
# Subgraph node function (entry point for the main graph)
# ---------------------------------------------------------------------------


async def research_subgraph(state: GraphState) -> GraphState:
    """LangGraph node: parallel stats + news fetch, then merge.

    Registered as a ``Subgraph`` node in Postgres.  Its three child nodes
    (stats_node, news_node, merge_node) are registered as ``Typical`` nodes
    with ``parent_node_id`` pointing to this subgraph.

    Execution order:
      1. stats_node + news_node run concurrently via ``asyncio.gather``.
      2. Their results are merged into state.
      3. merge_node runs with the combined data.

    Args:
        state: Current :class:`~backend.langgraph.state.GraphState`.

    Returns:
        Updated state with ``stats_data``, ``news_data``, and
        ``merged_research`` populated as serialised content model dicts.
    """
    thread_id: str = state["thread_id"]
    subgraph_node_id = make_node_id(thread_id, _SUBGRAPH_NAME)

    analysis = AnalyzeQueryOutput.model_validate(state.get("query_analysis", {}))

    subgraph_input = BaseNodeInput[AnalyzeQueryOutput](
        thread_id=thread_id,
        node_id=subgraph_node_id,
        node_name=_SUBGRAPH_NAME,
        content=analysis,
    )

    await upsert_node(
        thread_id=thread_id,
        node_id=subgraph_node_id,
        node_name=_SUBGRAPH_NAME,
        node_type=NodeType.SUBGRAPH,
        input_data=subgraph_input.content.model_dump(),
    )

    # ── Step 1: stats + news in parallel ──────────────────────────────
    try:
        stats_output, news_output = await asyncio.gather(
            _run_stats_node(state, subgraph_node_id, analysis),
            _run_news_node(state, subgraph_node_id, analysis),
        )
    except Exception as exc:
        await complete_node(
            thread_id=thread_id,
            node_id=subgraph_node_id,
            node_name=_SUBGRAPH_NAME,
            failed=True,
            error=str(exc),
        )
        raise

    # ── Step 2: merge (sequential, depends on both above) ─────────────
    merge_node_id = make_node_id(thread_id, _MERGE_NODE)
    merge_input = MergeResultsInput(
        stats_data=stats_output.model_dump(),
        news_data=news_output.model_dump(),
    )
    merge_node_input = BaseNodeInput[MergeResultsInput](
        thread_id=thread_id,
        node_id=merge_node_id,
        node_name=_MERGE_NODE,
        content=merge_input,
    )

    await upsert_node(
        thread_id=thread_id,
        node_id=merge_node_id,
        node_name=_MERGE_NODE,
        node_type=NodeType.TYPICAL,
        parent_node_id=subgraph_node_id,
        input_data=merge_node_input.content.model_dump(),
    )

    merge_task_input = BaseTaskInput[MergeResultsInput](
        thread_id=thread_id,
        node_id=merge_node_id,
        task_id=make_task_id(),
        task_name="merge_results",
        content=merge_input,
    )

    merge_exc: Exception | None = None
    merge_output: MergeResultsOutput | None = None
    try:
        merge_task_output: BaseTaskOutput[MergeResultsOutput] = await merge_results(merge_task_input)
        merge_output = merge_task_output.content
    except Exception as exc:
        merge_exc = exc
        await complete_node(
            thread_id=thread_id,
            node_id=merge_node_id,
            node_name=_MERGE_NODE,
            failed=True,
            error=str(exc),
        )

    if merge_exc is not None:
        await complete_node(
            thread_id=thread_id,
            node_id=subgraph_node_id,
            node_name=_SUBGRAPH_NAME,
            failed=True,
            error=str(merge_exc),
        )
        raise merge_exc

    merge_node_output = BaseNodeOutput[MergeResultsOutput](
        thread_id=thread_id,
        node_id=merge_node_id,
        node_name=_MERGE_NODE,
        content=merge_output,  # type: ignore[arg-type]
    )
    await complete_node(
        thread_id=thread_id,
        node_id=merge_node_id,
        node_name=_MERGE_NODE,
        output_data=merge_node_output.content.model_dump(),
    )

    subgraph_output = BaseNodeOutput[MergeResultsOutput](
        thread_id=thread_id,
        node_id=subgraph_node_id,
        node_name=_SUBGRAPH_NAME,
        content=merge_output,  # type: ignore[arg-type]
    )
    await complete_node(
        thread_id=thread_id,
        node_id=subgraph_node_id,
        node_name=_SUBGRAPH_NAME,
        output_data=subgraph_output.content.model_dump(),
    )

    return {
        **state,
        "stats_data": stats_output.model_dump(),
        "news_data": news_output.model_dump(),
        "merged_research": merge_output.model_dump(),  # type: ignore[union-attr]
    }
