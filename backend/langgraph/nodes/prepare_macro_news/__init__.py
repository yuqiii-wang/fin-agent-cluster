"""prepare_macro_news package -- Workflow node for macro-economic news fetch and digest."""

from backend.langgraph.nodes.prepare_macro_news.node import prepare_macro_news_node
from backend.langgraph.nodes.prepare_macro_news.models import (
    PrepareMacroNewsInput,
    PrepareMacroNewsOutput,
)

__all__ = [
    "prepare_macro_news_node",
    "PrepareMacroNewsInput",
    "PrepareMacroNewsOutput",
]
