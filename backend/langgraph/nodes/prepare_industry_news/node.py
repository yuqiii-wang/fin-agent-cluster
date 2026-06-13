"""PrepareIndustryNewsNode -- Workflow node that fetches and digests industry/sector news.

Hierarchy
---------
Thread
  └── prepare_industry_news  (Workflow)
        └── get_and_digest_news  (TaskSeq -> get_news + digest_news)  [×1]

Node design
-----------
The node reads ``stock_name`` from the ``query_node`` output to anchor the news
search to a relevant industry/sector context, then runs the
``get_and_digest_news`` pipeline to:

1. ``get_news``    -- fetch latest industry/sector news via FMP and web-search
                     snippets via DDGS, cache result in ``fin_markets.input_raw``.
2. ``digest_news`` -- enrich each article with LLM completion (ARK/Doubao),
                     embed the AI summary, and upsert to ``fin_markets.news_stats``.

Default topics: ``["industry", "sector", "competition", "regulation", "supply chain"]``.
Default lookback: 7 calendar days before the run date.

Predecessor
-----------
``query_node`` -- must be completed before ``prepare_industry_news`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_macro_stats``, ``prepare_index``,
``prepare_news``, and ``prepare_macro_news``.
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
from backend.langgraph.nodes.prepare_industry_news.models import (
    PrepareIndustryNewsInput,
    PrepareIndustryNewsOutput,
)
from backend.langgraph.nodes.prepare_industry_news.tasks.propose_industry_news_topics import (
    propose_industry_news_topics,
    ProposeIndustryNewsTopicsInput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS: int = 7
_NEWS_LIMIT: int = 20


class PrepareIndustryNewsNode(BaseNode[PrepareIndustryNewsInput, PrepareIndustryNewsOutput]):
    """Workflow node: fetches and digests industry/sector news for the queried stock."""

    node_name = "prepare_industry_news"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Industry News"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review industry news digest",
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
    tasks: ClassVar[list[NodeTask]] = [propose_industry_news_topics, *get_and_digest_news.tasks]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> PrepareIndustryNewsInput:
        """Construct node input -- resolves stock symbol from query_node output.

        Args:
            state: Current GraphState.

        Returns:
            :class:`PrepareIndustryNewsInput` with symbol, industry topics and date window.
        """
        symbol: str | None = None
        query_node_id = self._find_node_id_by_name(state, "query_node")
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_name: str = output.get("stock_name", "")
            if stock_name:
                symbol = stock_name
        else:
            logger.error("[PIN-001] query_node output unavailable; running topic-only industry news.")

        now = datetime.now(tz=timezone.utc)
        from_dt = now - timedelta(days=_LOOKBACK_DAYS)

        return PrepareIndustryNewsInput(
            symbol=symbol,
            topics=[],
            from_dt=from_dt,
            to_dt=now,
            news_limit=_NEWS_LIMIT,
        )

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[PrepareIndustryNewsInput, dict]:
        """Return a RunnableLambda that proposes industry topics then runs get_and_digest_news.

        First calls ``propose_industry_news_topics`` to dynamically derive industry-specific
        news topics via LLM, then passes those topics to ``get_and_digest_news``.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`PrepareIndustryNewsInput` and produces a keyed
            dict with ``__news_output__``.
        """
        async def _run(node_input: PrepareIndustryNewsInput) -> dict:
            # Step 1: propose industry-specific topics via LLM.
            # Soft failure -- if the proposal task raises, fall back to an empty
            # topic list so get_news still runs (symbol-only search).
            topics: list[str] = []
            try:
                propose_out = await self.run_task(
                    propose_industry_news_topics,
                    ctx,
                    ProposeIndustryNewsTopicsInput(stock_name=node_input.symbol or ""),
                )
                # Prepend the industry name itself so the news cache key and search
                # query include the sector context alongside the specific topic keywords.
                industry: str = propose_out.content.industry
                topics = (
                    ([industry] if industry else []) + propose_out.content.topics
                )
            except Exception as exc:
                logger.error(
                    "[PIN-002] propose_industry_news_topics failed symbol=%r: %s",
                    node_input.symbol,
                    exc,
                )

            # Step 2: fetch and digest news with the proposed topics.
            seq_out: GetAndDigestNewsOutput = await get_and_digest_news.run(
                self.run_task,
                ctx,
                GetAndDigestNewsInput(
                    symbol=node_input.symbol,
                    topics=topics,
                    from_dt=node_input.from_dt,
                    to_dt=node_input.to_dt,
                    news_limit=node_input.news_limit,
                ),
            )
            return {"__news_output__": seq_out, "__symbol__": node_input.symbol}

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> PrepareIndustryNewsOutput:
        """Compose node output from the task sequence result.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            :class:`PrepareIndustryNewsOutput` with industry news digest summary.
        """
        seq_out: GetAndDigestNewsOutput | None = results.get("__news_output__")
        symbol: str | None = results.get("__symbol__")
        if seq_out is None:
            return PrepareIndustryNewsOutput(symbol=symbol)

        return PrepareIndustryNewsOutput(
            symbol=symbol,
            input_raw_id=seq_out.get_news.input_raw_id,
            upserted_ids=seq_out.digest_news.upserted_ids,
            news_articles_count=len(seq_out.get_news.news_articles),
            from_cache=seq_out.get_news.from_cache,
            markdown=seq_out.digest_news.markdown,
        )

    def get_state_updates(self, output: PrepareIndustryNewsOutput) -> dict[str, Any]:
        """No GraphState updates -- output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


prepare_industry_news_node = PrepareIndustryNewsNode()
