"""Graph state schema for the fin-analysis LangGraph.

Hierarchy
---------
Thread (thread_id)
  └── Node  (e.g. query_node, stats_node, news_node, merge_node, conclusion_node)
        └── Task  (e.g. analyze_query, read_stats, read_news, merge_results, stream_conclusion)

Every field is optional so each node only needs to populate its own outputs;
previous node results are preserved across checkpoints automatically.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class GraphState(TypedDict, total=False):
    # ── Thread-level identity ─────────────────────────────────────────
    thread_id: str
    user_id: str
    query: str
    test_config: Optional[dict[str, Any]]  # For internal testing purposes; ignored in production.

    # ── query_node output ─────────────────────────────────────────────
    # Result of the analyze_query task:
    #   {"intent": str, "symbols": list[str], "filters": dict}
    query_analysis: dict[str, Any]

    # ── research subgraph outputs ─────────────────────────────────────
    # Result of the read_stats task:
    #   {"records": list[dict], "symbol": str, "interval": str}
    stats_data: dict[str, Any]

    # Result of the read_news task:
    #   {"articles": list[dict], "symbol": str}
    news_data: dict[str, Any]

    # Result of the merge_results task:
    #   {"summary": str, "stats": ..., "news": ...}
    merged_research: dict[str, Any]

    # ── conclusion_node output ────────────────────────────────────────
    # Full concatenated streaming answer; persisted to fin_agents.llm_responses
    conclusion: Optional[str]

    # ── Error propagation (any node can set this) ─────────────────────
    error: Optional[str]
