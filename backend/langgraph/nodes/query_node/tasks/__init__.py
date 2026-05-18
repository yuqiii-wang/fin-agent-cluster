"""Tasks for query_node."""

from backend.langgraph.nodes.query_node.tasks.analyze_query import analyze_query
from backend.langgraph.nodes.query_node.tasks.get_stock_from_web_if_not_seen import get_stock_from_web_if_not_seen
from backend.langgraph.nodes.query_node.tasks.analyze_stock_from_web_if_not_seen import (
    analyze_stock_from_web_if_not_seen,
    STREAM_PROMPT_BUILDERS,
)
from backend.langgraph.nodes.query_node.tasks.get_stock_region import get_stock_region
from backend.langgraph.nodes.query_node.tasks.get_stock_industry_peers import get_stock_industry_peers

HANDLERS: dict = {
    analyze_query.name: analyze_query.handler,
    get_stock_from_web_if_not_seen.name: get_stock_from_web_if_not_seen.handler,
    get_stock_region.name: get_stock_region.handler,
    get_stock_industry_peers.name: get_stock_industry_peers.handler,
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
