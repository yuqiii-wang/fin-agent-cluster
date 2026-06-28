"""LoadPeersStatsNode -- Workflow node that fetches and computes OHLCV stats
for peer tickers proposed by ``prepare_peers``.

Hierarchy
---------
Thread
  └── load_peers_stats  (Workflow)
        └── get_and_calculate_stats  (TaskSeq -> get_stats + calculate_stats)  [×N peers, parallel]

Node design
-----------
Reads ``proposed_peers`` from ``prepare_peers``'s completed node_executions
row, then runs the shared ``get_and_calculate_stats`` TaskSeq in parallel for
each peer ticker to fetch raw OHLCV data and compute technical indicators.

Predecessor
-----------
``prepare_peers`` -- must be completed before ``load_peers_stats`` starts.
This node is a pure continuation of ``prepare_peers`` and is NOT part of the
``analyze_parallel`` fan-out group, so it does NOT wait for siblings like
``prepare_macro_stats``, ``prepare_news``, or ``prepare_index`` to finish.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    GetAndCalculateStatsInput,
    get_and_calculate_stats,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.load_peers_stats.models import (
    LoadPeersStatsInput,
    LoadPeersStatsOutput,
    PeerStatsResult,
)
from backend.langgraph.state import GraphState
from backend.quant.stats import STATS_VIEW_TYPE

logger = logging.getLogger(__name__)

_STATS_PERIOD: str = "1y"


class LoadPeersStatsNode(BaseNode[LoadPeersStatsInput, LoadPeersStatsOutput]):
    """Workflow node: fetches and computes OHLCV stats for peer tickers."""

    node_name = "load_peers_stats"
    node_type = NodeType.WORKFLOW
    display_name = "Load Peers Stats"
    category = "Analysis"
    # NOTE: no parallel_group / parallel_branch here.  This node is a pure
    # continuation of ``prepare_peers`` and should NOT be treated as a sibling
    # of the other ``analyze_parallel`` branches (prepare_macro_stats,
    # prepare_news, prepare_index, ...).  Its only dependency is ``prepare_peers``
    # (declared in _prev_node_names); it runs as soon as that single predecessor
    # finishes, independently of the rest of the analysis fan-out.
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review peer stats",
            "type": "boolean",
            "description": "Pause after peer stats are computed; wait for your approval.",
        },
    ]
    view_type = "Stats"
    stats_views = [STATS_VIEW_TYPE.STACK_CANDLE_STICK.value]
    tasks: ClassVar[list[NodeTask]] = [*get_and_calculate_stats.tasks]
    _prev_node_names: ClassVar[list[str]] = ["prepare_peers"]

    async def build_input(self, state: GraphState) -> LoadPeersStatsInput:
        """Construct node input -- reads proposed_peers from prepare_peers output.

        Args:
            state: Current GraphState.

        Returns:
            :class:`LoadPeersStatsInput` populated from the PG replica.
        """
        peers_node_id = self._find_node_id_by_name(state, "prepare_peers")
        peers: list[str] = []
        if peers_node_id:
            output = await read_node_output(peers_node_id)
            peers = list(output.get("proposed_peers", []) or [])
        else:
            logger.error(
                "[LPS-001] prepare_peers output unavailable; peers will be empty."
            )
        return LoadPeersStatsInput(peers=peers, period=_STATS_PERIOD)

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[LoadPeersStatsInput, dict]:
        """Return a RunnableLambda that runs get_and_calculate_stats in parallel
        for every peer ticker.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`LoadPeersStatsInput` and returns a
            keyed dict with ``__peer_results__`` and ``__df_splits__``.
        """

        async def _run(node_input: LoadPeersStatsInput) -> dict:
            if not node_input.peers:
                logger.warning(
                    "[LPS-002] prepare_peers returned no peers; skipping stats fetch."
                )
                return {"__peer_results__": [], "__df_splits__": []}

            async def _fetch_peer(symbol: str) -> tuple[PeerStatsResult, dict] | None:
                """Fetch and compute OHLCV stats for a single peer; returns (result, df_split) or None on error."""
                try:
                    seq_out = await get_and_calculate_stats.run(
                        self.run_task,
                        ctx,
                        GetAndCalculateStatsInput(
                            symbol=symbol,
                            period=node_input.period,
                        ),
                    )
                    result = PeerStatsResult(
                        symbol=symbol,
                        rows_upserted=seq_out.calculate_stats.rows_upserted,
                        granularity=seq_out.calculate_stats.granularity,
                        source=seq_out.calculate_stats.source,
                        from_cache=seq_out.get_stats.from_cache,
                    )
                    return result, seq_out.calculate_stats.df_split
                except Exception as exc:
                    logger.error(
                        "[LPS-003] Peer stats failed symbol=%r: %s", symbol, exc
                    )
                    return None

            raw = await asyncio.gather(*[_fetch_peer(p) for p in node_input.peers])
            pairs = [r for r in raw if r is not None]
            peer_results = [p[0] for p in pairs]
            df_splits = [
                {
                    "symbol": p[0].symbol,
                    "label": p[0].symbol,
                    "df_split": p[1],
                }
                for p in pairs
                if p[1]
            ]

            if not peer_results and node_input.peers:
                logger.error("[LPS-004] All peer stats fetches failed.")

            return {
                "__peer_results__": peer_results,
                "__df_splits__": df_splits,
            }

        return RunnableLambda(_run)

    def build_output(self, results: dict) -> LoadPeersStatsOutput:
        """Compose node output from the parallel peer stats results.

        Args:
            results: Keyed task outputs from the chain.

        Returns:
            :class:`LoadPeersStatsOutput` with per-peer stats results.
        """
        return LoadPeersStatsOutput(
            peers=results.get("__peer_results__", []),
            period=_STATS_PERIOD,
            df_splits=results.get("__df_splits__", []),
        )

    def get_state_updates(self, output: LoadPeersStatsOutput) -> dict[str, Any]:
        """No GraphState updates -- output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


# Module-level callable registered with LangGraph StateGraph.
load_peers_stats_node = LoadPeersStatsNode()
