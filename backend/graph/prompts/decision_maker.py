"""Prompt template for the decision_maker agent node."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


def build_prompt_template() -> ChatPromptTemplate:
    """Return the ChatPromptTemplate for the decision_maker node.

    The template accepts two variables:
    - ``query``: raw user query string.
    - ``market_data_context``: pre-fetched market data formatted as text.

    The LLM must return a JSON object whose keys match the columns of
    ``fin_strategies.reports`` (excluding ``id``, ``symbol``, ``created_at``).

    Returns:
        A :class:`~langchain_core.prompts.ChatPromptTemplate` for the
        decision_maker node.
    """
    return ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a senior quantitative analyst and portfolio strategist. "
            "Using ONLY the market data provided, produce a structured trading decision report. "
            "Do NOT invent figures or reference data not supplied.\n\n"
            "Respond with a single valid JSON object (no markdown fences) with these keys.\n"
            "Fields marked (required) MUST be present and non-empty.\n"
            "Fields marked (optional) may be omitted or set to null when not applicable.\n\n"
            "REQUIRED fields:\n"
            "  short_term_technical_desc  — short-term technical analysis (1-2 weeks outlook)\n"
            "  long_term_technical_desc   — long-term technical analysis (6m+ outlook)\n"
            "  news_desc                  — concise news/sentiment summary\n"
            "  basic_biz_desc             — company business overview and fundamentals\n"
            "  industry_desc              — industry dynamics and competitive landscape\n\n"
            "OPTIONAL fields:\n"
            "  significant_event_desc      — earnings, product launches, M&A, or other significant events\n"
            "  short_term_risk_desc        — key risks over the next 1-2 weeks\n"
            "  long_term_risk_desc         — key risks over 6+ months\n"
            "  short_term_growth_desc      — growth catalysts over the next 1-2 weeks\n"
            "  long_term_growth_desc       — growth catalysts over 6+ months\n"
            "  recent_trade_anomalies      — signals of market manipulation, price suppression, unusual volume\n"
            "  likely_today_fall_desc      — reasoning for a potential price fall today (near afternoon given morning data; if market not yet open, base on yesterday/history)\n"
            "  likely_tom_fall_desc        — reasoning for a potential price fall tomorrow\n"
            "  likely_short_term_fall_desc — reasoning for a potential fall in the next 1-2 weeks\n"
            "  likely_long_term_fall_desc  — reasoning for a potential fall over 6+ months\n"
            "  likely_today_rise_desc      — reasoning for a potential price rise today (near afternoon given morning data; if market not yet open, base on yesterday/history)\n"
            "  likely_tom_rise_desc        — reasoning for a potential price rise tomorrow\n"
            "  likely_short_term_rise_desc — reasoning for a potential rise in the next 1-2 weeks\n"
            "  likely_long_term_rise_desc  — reasoning for a potential rise over 6+ months\n"
            "Output nothing except the JSON object.",
        ),
        (
            "human",
            "User query: {query}\n\n"
            "Market data:\n{market_data_context}",
        ),
    ])
