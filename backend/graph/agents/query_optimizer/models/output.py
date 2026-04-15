"""QueryOptimizerOutput: final structured output of the query_optimizer node."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.graph.agents.query_optimizer.models.news import NewsContext
from backend.graph.agents.query_optimizer.models.quant import QuantContext


class QueryOptimizerOutput(BaseModel):
    """Structured output from query_optimizer passed to market_data_collector.

    Produced by the query_optimizer node after LLM parsing and template population.
    Contains nested quant and news sub-contexts used by downstream nodes.

    Task flow (all sequential):
      1. ``comprehend_basics`` — Input: ``{"query": str}``; Output: raw JSON string
      2. ``populate_json``     — Input: raw JSON; Output: :class:`QueryOptimizerOutput`
    """

    query: str = Field(..., description="Original user query string")
    quants: QuantContext = Field(..., description="Quant data collection parameters")
    news: NewsContext = Field(..., description="News search query parameters")
