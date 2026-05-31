"""PrepareMacroNewsNode — Workflow node that fetches and digests macro-economic news.

Hierarchy
---------
Thread
  └── prepare_macro_news  (Workflow)
        └── get_and_digest_news  (TaskSeq → get_news + digest_news)  [×1]

Node design
-----------
The node runs the ``get_and_digest_news`` pipeline with macro-economic topics
(Fed policy, inflation, GDP, interest rates, geopolitics) rather than a specific
stock symbol.  The optional stock symbol from ``query_node`` is carried through
purely for downstream contextual correlation.

1. ``get_news``    — fetch latest macro-economic news via FMP and web-search
                     snippets via DDGS, cache result in ``fin_markets.input_raw``.
2. ``digest_news`` — enrich each article with LLM completion (ARK/Doubao),
                     embed the AI summary, and upsert to ``fin_markets.news_stats``.

Default topics: ``["federal reserve", "inflation", "gdp", "interest rates",
                   "monetary policy", "geopolitics", "trade policy"]``.
Default lookback: 7 calendar days before the run date.

Predecessor
-----------
``query_node`` — must be completed before ``prepare_macro_news`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_macro_stats``, ``prepare_index``,
``prepare_news``, and ``prepare_industry_news``.
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
from backend.langgraph.nodes.prepare_macro_news.models import (
    PrepareMacroNewsInput,
    PrepareMacroNewsOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)

_DEFAULT_TOPICS: list[str] = [
    "federal reserve",
    "inflation",
    "gdp",
    "interest rates",
    "monetary policy",
    "geopolitics",
    "trade policy",
]
_LOOKBACK_DAYS: int = 7
_NEWS_LIMIT: int = 20


class PrepareMacroNewsNode(BaseNode[PrepareMacroNewsInput, PrepareMacroNewsOutput]):
    """Workflow node: fetches and digests macro-economic news."""

    node_name = "prepare_macro_news"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Macro News"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review macro news digest",
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

    async def build_input(self, state: GraphState) -> PrepareMacroNewsInput:
        """Construct node input — optionally reads stock symbol from query_node output.

        Args:
            state: Current GraphState.

        Returns:
            :class:`PrepareMacroNewsInput` with macro topics and date window.
            Symbol is carried as optional context but not used for news filtering.
        """
        symbol: str | None = None
        query_node_id = self._find_node_id_by_name(state, "query_node")
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_name: str = output.get("stock_name", "")
            if stock_name:
                symbol = stock_name
        else:
            logger.error("[PMN-001] query_node output unavailable; running topic-only macro news.")

        now = datetime.now(tz=timezone.utc)
        from_dt = now - timedelta(days=_LOOKBACK_DAYS)

        return PrepareMacroNewsInput(
            symbol=symbol,
            topics=_DEFAULT_TOPICS,
            from_dt=from_dt,
            to_dt=now,
            news_limit=_NEWS_LIMIT,
        )

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[PrepareMacroNewsInput, dict]:
        """Return a RunnableLambda that runs get_and_digest_news for macro-economic news.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`PrepareMacroNewsInput` and produces a keyed
            dict with ``__news_output__``.
        """
        async def _run(node_input: PrepareMacroNewsInput) -> dict:
            seq_out: GetAndDigestNewsOutput = await get_and_digest_news.run(
                self.run_task,
                ctx,
                GetAndDigestNewsInput(
                    symbol=None,
                    topics=node_input.topics,
                    from_dt=node_input.from_dt,
                    to_dt=node_input.to_dt,
                    news_limit=node_input.news_limit,
                ),
            )
            return {"__news_output__": seq_out, "__symbol__": node_input.symbol}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> PrepareMacroNewsOutput:
        """Compose node output from the task sequence result.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            :class:`PrepareMacroNewsOutput` with macro news digest summary.
        """
        seq_out: GetAndDigestNewsOutput | None = results.get("__news_output__")
        symbol: str | None = results.get("__symbol__")
        if seq_out is None:
            return PrepareMacroNewsOutput(symbol=symbol)

        return PrepareMacroNewsOutput(
            symbol=symbol,
            input_raw_id=seq_out.get_news.input_raw_id,
            upserted_ids=seq_out.digest_news.upserted_ids,
            news_articles_count=len(seq_out.get_news.news_articles),
            from_cache=seq_out.get_news.from_cache,
            markdown=seq_out.digest_news.markdown,
        )

    def get_state_updates(self, output: PrepareMacroNewsOutput) -> dict[str, Any]:
        """No GraphState updates — output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


prepare_macro_news_node = PrepareMacroNewsNode()
