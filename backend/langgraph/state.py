"""Graph state schema for the fin-analysis LangGraph.

Hierarchy
---------
Thread (thread_id)
  └── Node  (e.g. query_node, stats_node, news_node, merge_node, conclusion_node)
        └── Task  (e.g. analyze_query, read_stats, read_news, merge_results, stream_conclusion)

Every field is optional so each node only needs to populate its own outputs;
previous node results are preserved across checkpoints automatically.

State-to-SQL mapping
--------------------
GraphState field   SQL column (fin_agents.*)           Typed shape
-----------------  -----------------------------------  ----------------------------
query              user_queries.query                   str
query_analysis     tasks.output (analyze_query)         AnalyzeQueryOutput (as dict)
stats_data         tasks.output (read_stats)            ReadStatsOutput (as dict)
news_data          tasks.output (read_news)             ReadNewsOutput (as dict)
merged_research    tasks.output (merge_results)         MergeResultsOutput (as dict)
conclusion         user_queries.answer                  str

All node/task JSONB payloads are the ``model_dump()`` of the corresponding
content model.  Nodes deserialise via ``model_validate`` when they need to
pass typed values downstream.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class GraphState(TypedDict, total=False):
    # ── Thread-level identity ─────────────────────────────────────────
    thread_id: str
    user_id: str
    query: str

    # ── query_node output ─────────────────────────────────────────────
    # Serialised AnalyzeQueryOutput: {"intent": str, "symbols": list[str], "filters": dict}
    query_analysis: dict[str, Any]

    # ── research subgraph outputs ─────────────────────────────────────
    # Serialised ReadStatsOutput: {"symbol": str, "interval": str, "records": list[dict]}
    stats_data: dict[str, Any]

    # Serialised ReadNewsOutput: {"symbol": str, "articles": list[dict]}
    news_data: dict[str, Any]

    # Serialised MergeResultsOutput: {"symbol": str, "summary": str, "stats": dict, "news": dict}
    merged_research: dict[str, Any]

    # ── conclusion_node output ────────────────────────────────────────
    # Full concatenated streaming answer; persisted to fin_agents.user_queries.answer
    conclusion: Optional[str]

    # ── Error propagation (any node can set this) ─────────────────────
    error: Optional[str]
