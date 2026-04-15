"""Prompt template for the market_data_collector synthesis step."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


def build_prompt_template() -> ChatPromptTemplate:
    """Return the ChatPromptTemplate for market data synthesis.

    The template accepts two variables:
    - ``query``: raw user query string.
    - ``real_data_context``: pre-fetched market data formatted as a text block.

    Returns:
        A :class:`~langchain_core.prompts.ChatPromptTemplate` for the
        market data synthesis chain.
    """
    return ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a financial data analyst. Synthesise the provided real market data "
            "into a structured, comprehensive market analysis. "
            "Base your analysis solely on the supplied data — do not invent figures. "
            "Cover: current price action and key metrics, OHLCV trends across all "
            "timeframes, futures contract positioning (if available), options flow and "
            "sentiment (if available), peer comparisons, and significant news events.",
        ),
        (
            "human",
            "User query: {query}\n\n"
            "Real market data retrieved:\n{real_data_context}\n\n"
            "Synthesise the above into a comprehensive market data summary. "
            "Respond in English.",
        ),
    ])
