"""Tasks for query_node."""

from backend.langgraph.nodes.query_node.tasks.analyze_query import (
    analyze_query,
    STREAM_PROMPT_BUILDERS as _AQ_BUILDERS,
)
from backend.langgraph.nodes.query_node.tasks.get_stock_from_web_if_not_seen import get_stock_from_web_if_not_seen
from backend.langgraph.nodes.query_node.tasks.analyze_stock_from_web_if_not_seen import (
    analyze_stock_from_web_if_not_seen,
    STREAM_PROMPT_BUILDERS as _AWSN_BUILDERS,
)
from backend.langgraph.nodes.query_node.tasks.get_stock_region import (
    get_stock_region,
    STREAM_PROMPT_BUILDERS as _GSR_BUILDERS,
)
from backend.langgraph.nodes.query_node.tasks.get_stock_industry_peers import (
    get_stock_industry_peers,
    STREAM_PROMPT_BUILDERS as _GSIP_BUILDERS,
)

HANDLERS: dict = {
    get_stock_from_web_if_not_seen.name: get_stock_from_web_if_not_seen.handler,
}

STREAM_PROMPT_BUILDERS: dict = {
    **_AQ_BUILDERS,
    **_AWSN_BUILDERS,
    **_GSR_BUILDERS,
    **_GSIP_BUILDERS,
}

__all__ = [
    "analyze_query",
    "get_stock_from_web_if_not_seen",
    "analyze_stock_from_web_if_not_seen",
    "get_stock_region",
    "get_stock_industry_peers",
    "HANDLERS",
    "STREAM_PROMPT_BUILDERS",
]
