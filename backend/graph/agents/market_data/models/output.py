"""MarketDataOutput: final structured output of the market_data_collector node."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.graph.agents.market_data.models.news import NewsRawResults
from backend.graph.agents.market_data.models.quant import QuantCollectionResult


class MarketDataOutput(BaseModel):
    """Structured JSON output from the market_data_collector node.

    Aggregates all quant and news sub-task results alongside the LLM-synthesised
    market summary.  Stored in ``state["market_data_json"]`` so downstream
    analysis nodes can access structured data without re-parsing text.

    Task flow overview:
      Sequential:
        1. ``parse_input``   — validate :class:`QueryOptimizerOutput` from state
      Parallel (asyncio.gather):
        2a. ``ohlcv_*``        — 4 OHLCV windows (15min / 1h / 1day / 1mo) for main ticker
        2b. ``company_news``   — yfinance company news
        2c. ``web_search_*``   — N named search queries (one per NewsContext field)
        2d. ``peer_ohlcv_*``   — 2 peer ticker 1y daily OHLCV
        2e. ``macro_*``        — 7 macro tickers (gold, crude_oil, natural_gas, sofr_on, sofr_tn, sofr_1m, bitcoin)
        2f. ``bond``           — US Bond yield curve
        2g. ``index_ohlcv_*``  — ticker benchmark index 1y daily OHLCV (if available)
      Sequential (after gather):
        3. ``llm_synthesis`` — assemble context_lines → LLM summary
    """

    ticker: str = Field(..., description="Primary ticker symbol")
    query: str = Field("", description="Original user query")
    quant: QuantCollectionResult = Field(
        default_factory=QuantCollectionResult,
        description="All quant sub-task results",
    )
    news: list[NewsRawResults] = Field(
        default_factory=list,
        description="All news sub-task results (company news + web searches)",
    )
    summary: str = Field("", description="LLM-synthesised market analysis text")

    def to_context_lines(self) -> list[str]:
        """Build the full context string for LLM synthesis from structured sub-results."""
        lines: list[str] = [f"=== Real Market Data for {self.ticker} ==="]
        lines.extend(self.quant.to_context_lines())
        for news_result in self.news:
            lines.extend(news_result.to_context_lines())
        return lines
