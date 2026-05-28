"""PrepareNewsNode — Workflow node that fetches and digests news for the queried stock.

Hierarchy
---------
Thread
  └── prepare_news  (Workflow)
        └── get_and_digest_news  (TaskSeq → get_news + digest_news)  [×1]

Node design
-----------
The node reads ``stock_name`` from the ``query_node`` output, uses it as the
primary news symbol, and runs the ``get_and_digest_news`` pipeline to:

1. ``get_news``    — fetch latest news via FMP and web-search snippets via
                     DDGS, cache result in ``fin_markets.news_raw``.
2. ``digest_news`` — enrich each article with LLM completion (ARK/Doubao),
                     embed the AI summary, and upsert to ``fin_markets.news_stats``.

Default topics: ``["earnings", "analyst", "market", "fundamentals"]``.
Default lookback: 7 calendar days before the run date.

Predecessor
-----------
``query_node`` — must be completed before ``prepare_news`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_macro_stats``, and ``prepare_index``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news import (
    get_and_digest_news,
    GetAndDigestNewsInput,
    GetAndDigestNewsOutput,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_news.models import PrepareNewsInput, PrepareNewsOutput
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)

_DEFAULT_TOPICS: list[str] = ["earnings", "analyst", "market", "fundamentals"]
_LOOKBACK_DAYS: int = 7
_NEWS_LIMIT: int = 20


class PrepareNewsNode(BaseNode[PrepareNewsInput, PrepareNewsOutput]):
    """Workflow node: fetches and digests news for the queried stock."""

    node_name = "prepare_news"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare News"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review news digest",
            "type": "boolean",
            "description": "Pause after news is fetched and digested; wait for your approval.",
        },
        {
            "key": "lookback_days",
            "label": "Lookback days",
            "type": "number",
            "description": "How many calendar days of news history to fetch (default 7).",
        },
    ]
    view_type = "Markdown"
    tasks: ClassVar[list[NodeTask]] = [*get_and_digest_news.tasks]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> PrepareNewsInput:
        """Construct node input — resolves stock symbol from query_node output.

        Args:
            state: Current GraphState.

        Returns:
            :class:`PrepareNewsInput` with symbol, default topics and date window.
        """
        symbol: str | None = None
        query_node_id = self._find_node_id_by_name(state, "query_node")
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_name: str = output.get("stock_name", "")
            if stock_name:
                symbol = stock_name
        else:
            logger.error("[PN-001] query_node output unavailable; running topic-only news.")

        now = datetime.now(tz=timezone.utc)
        from_dt = now - timedelta(days=_LOOKBACK_DAYS)

        return PrepareNewsInput(
            symbol=symbol,
            topics=_DEFAULT_TOPICS,
            from_dt=from_dt,
            to_dt=now,
            news_limit=_NEWS_LIMIT,
        )

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[PrepareNewsInput, dict]:
        """Return a RunnableLambda that runs get_and_digest_news for the stock.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`PrepareNewsInput` and produces a keyed
            dict with ``__news_output__``.
        """
        async def _run(node_input: PrepareNewsInput) -> dict:
            seq_out: GetAndDigestNewsOutput = await get_and_digest_news.run(
                self.run_task,
                ctx,
                GetAndDigestNewsInput(
                    symbol=node_input.symbol,
                    topics=node_input.topics,
                    from_dt=node_input.from_dt,
                    to_dt=node_input.to_dt,
                    news_limit=node_input.news_limit,
                ),
            )
            return {"__news_output__": seq_out, "__symbol__": node_input.symbol}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> PrepareNewsOutput:
        """Compose node output from the task sequence result.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            :class:`PrepareNewsOutput` with news digest summary.
        """
        seq_out: GetAndDigestNewsOutput | None = results.get("__news_output__")
        symbol: str | None = results.get("__symbol__")
        if seq_out is None:
            return PrepareNewsOutput(symbol=symbol)

        return PrepareNewsOutput(
            symbol=symbol,
            news_raw_id=seq_out.get_news.news_raw_id,
            upserted_ids=seq_out.digest_news.upserted_ids,
            news_articles_count=len(seq_out.get_news.news_articles),
            from_cache=seq_out.get_news.from_cache,
            markdown=seq_out.digest_news.markdown,
        )

    def get_state_updates(self, output: PrepareNewsOutput) -> dict[str, Any]:
        """No GraphState updates — output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


prepare_news_node = PrepareNewsNode()
