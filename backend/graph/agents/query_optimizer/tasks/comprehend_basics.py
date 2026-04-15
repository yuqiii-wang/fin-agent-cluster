"""Task 1 — comprehend_basics: stream LLM JSON output for the query_optimizer node.

Input:  chain (Runnable), query, thread_id, node_execution_id, provider
Output: raw JSON string, or None on failure
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.runnables import Runnable

from backend.graph.agents.task_keys import QO_COMPREHEND_BASICS
from backend.graph.utils.task_stream import complete_task, create_task, fail_task, stream_text_task

logger = logging.getLogger(__name__)


async def comprehend_basics(
    chain: Runnable,
    query: str,
    thread_id: str,
    node_execution_id: int,
    provider: str,
) -> Optional[str]:
    """Stream raw JSON from the LLM chain to extract core identity fields.

    Creates the ``comprehend_basics`` task entry, streams LLM output,
    and marks the task complete or failed.

    Args:
        chain:             LangChain chain from :func:`~backend.graph.agents.query_optimizer.chain.build_chain`.
        query:             Raw user query string.
        thread_id:         LangGraph thread id.
        node_execution_id: Parent node-execution id for task tracking.
        provider:          Active LLM provider name for task metadata.

    Returns:
        Raw JSON string on success, or ``None`` on failure.
    """
    task_id = await create_task(
        thread_id, QO_COMPREHEND_BASICS, node_execution_id, provider=provider
    )
    try:
        raw_json = await stream_text_task(
            thread_id,
            task_id,
            QO_COMPREHEND_BASICS,
            chain.astream({"query": query}),
        )
        await complete_task(
            thread_id, task_id, QO_COMPREHEND_BASICS,
            {"raw_json_len": len(raw_json)},
        )
        return raw_json
    except Exception as exc:
        logger.warning("[query_optimizer] comprehend_basics failed: %s", exc)
        await fail_task(thread_id, task_id, QO_COMPREHEND_BASICS, str(exc))
        return None
