"""Nodes package for the fin-trading LangGraph.

Exports
-------
Node callables (registered with LangGraph StateGraph):
    query_node, prepare_peers_node, load_peers_stats_node, prepare_macro_stats_node,
    prepare_index_node, prepare_news_node, prepare_industry_news_node,
    prepare_macro_news_node, prepare_options_node, prepare_futures_node,
    prepare_fundamentals_node, load_symbol_stats_node, final_report_node

HANDLERS registry (consumed by the Celery completion worker):
    Flat dict mapping task_name -> async handler assembled from each node's
    tasks sub-package.  Streaming tasks (stream_llm) are excluded
    because they run via a separate Celery stream worker.

STREAM_PROMPT_BUILDERS registry (consumed by the Celery stream worker):
    Flat dict mapping task_name -> callable that builds a (ChatPromptTemplate, parser)
    pair for streaming LLM steps.

NODE_REGISTRY:
    Flat dict mapping node_name -> BaseNode instance.  Used by the
    agent capabilities API to look up NodeTask descriptions and input
    schemas without hitting the DB.
"""

from backend.langgraph.nodes.query_node import query_node
from backend.langgraph.nodes.query_node import HANDLERS as _QH
from backend.langgraph.nodes.query_node.tasks import STREAM_PROMPT_BUILDERS as _Q_STREAM
from backend.langgraph.nodes.prepare_peers import prepare_peers_node
from backend.langgraph.nodes.prepare_peers import STREAM_PROMPT_BUILDERS as _PP_STREAM
from backend.langgraph.nodes.load_peers_stats import load_peers_stats_node
from backend.langgraph.nodes.prepare_macro_stats import prepare_macro_stats_node
from backend.langgraph.nodes.prepare_index import prepare_index_node
from backend.langgraph.nodes.prepare_news import prepare_news_node
from backend.langgraph.nodes.prepare_industry_news import prepare_industry_news_node
from backend.langgraph.nodes.prepare_industry_news import STREAM_PROMPT_BUILDERS as _PIN_STREAM
from backend.langgraph.nodes.prepare_macro_news import prepare_macro_news_node
from backend.langgraph.nodes.prepare_options import prepare_options_node
from backend.langgraph.nodes.prepare_options import HANDLERS as _POH
from backend.langgraph.nodes.prepare_futures import prepare_futures_node
from backend.langgraph.nodes.prepare_futures import HANDLERS as _PFH
from backend.langgraph.nodes.prepare_fundamentals import prepare_fundamentals_node
from backend.langgraph.nodes.load_symbol_stats import load_symbol_stats_node
from backend.langgraph.nodes.final_report import final_report_node
from backend.langgraph.models.common_tasks import HANDLERS as _CTH
from backend.langgraph.models.common_tasks import STREAM_PROMPT_BUILDERS as _CT_STREAM

# Global HANDLERS registry consumed by completion_task.run_completion.
HANDLERS: dict = {**_QH, **_CTH, **_POH, **_PFH}

# Global STREAM_PROMPT_BUILDERS registry consumed by stream_task.run_stream.
STREAM_PROMPT_BUILDERS: dict = {
    **_Q_STREAM,
    **_PP_STREAM,
    **_PIN_STREAM,
    **_CT_STREAM,
}

# Registry mapping node_name -> node instance.
NODE_REGISTRY: dict = {
    node.node_name: node
    for node in [
        query_node,
        prepare_peers_node,
        load_peers_stats_node,
        prepare_macro_stats_node,
        prepare_index_node,
        prepare_news_node,
        prepare_industry_news_node,
        prepare_macro_news_node,
        prepare_options_node,
        prepare_futures_node,
        prepare_fundamentals_node,
        load_symbol_stats_node,
        final_report_node,
    ]
}

__all__ = [
    "query_node",
    "prepare_peers_node",
    "load_peers_stats_node",
    "prepare_macro_stats_node",
    "prepare_index_node",
    "prepare_news_node",
    "prepare_industry_news_node",
    "prepare_macro_news_node",
    "prepare_options_node",
    "prepare_futures_node",
    "prepare_fundamentals_node",
    "load_symbol_stats_node",
    "final_report_node",
    "HANDLERS",
    "STREAM_PROMPT_BUILDERS",
    "NODE_REGISTRY",
]
