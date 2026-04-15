"""DecisionReport: structured output model for the decision_maker node.

Maps directly to the columns of ``fin_strategies.reports`` (excluding ``id``,
``symbol``, and ``created_at`` which are managed by the DB).

Required fields (NOT NULL in DB): ``short_term_technical_desc``,
``long_term_technical_desc``, ``news_desc``, ``basic_biz_desc``, ``industry_desc``.
All other fields are nullable (TEXT in DB) and represented as ``Optional[str]``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DecisionReport(BaseModel):
    """Structured trading decision report produced by the LLM.

    Required fields mirror the NOT NULL constraints in ``fin_strategies.reports``.
    Nullable DB columns use ``Optional[str] = None``.
    """

    # --- Required (NOT NULL in fin_strategies.reports) -----------------------
    short_term_technical_desc: str = Field(..., description="Short-term technical analysis summary")
    long_term_technical_desc: str = Field(..., description="Long-term technical analysis summary")
    news_desc: str = Field(..., description="News and sentiment summary")
    basic_biz_desc: str = Field(..., description="Basic business overview and fundamentals")
    industry_desc: str = Field(..., description="Industry dynamics and competitive landscape")

    # --- Optional (nullable TEXT in fin_strategies.reports) ------------------
    significant_event_desc: Optional[str] = Field(
        None, description="Significant events: earnings, product launches, M&A, etc."
    )
    short_term_risk_desc: Optional[str] = Field(None, description="Key risks over the next 1-2 weeks")
    long_term_risk_desc: Optional[str] = Field(None, description="Key risks over 6+ months")
    short_term_growth_desc: Optional[str] = Field(None, description="Growth catalysts over the next 1-2 weeks")
    long_term_growth_desc: Optional[str] = Field(None, description="Growth catalysts over 6+ months")
    recent_trade_anomalies: Optional[str] = Field(
        None, description="Signals of market manipulation, price suppression, unusual volume, etc."
    )
    likely_today_fall_desc: Optional[str] = Field(
        None, description="Reasoning for a potential price fall today (near afternoon given morning data; if market not yet open, base on yesterday/history)"
    )
    likely_tom_fall_desc: Optional[str] = Field(
        None, description="Reasoning for a potential price fall tomorrow"
    )
    likely_short_term_fall_desc: Optional[str] = Field(
        None, description="Reasoning for a potential fall in the next 1-2 weeks"
    )
    likely_long_term_fall_desc: Optional[str] = Field(
        None, description="Reasoning for a potential fall over 6+ months"
    )
    likely_today_rise_desc: Optional[str] = Field(
        None, description="Reasoning for a potential price rise today (near afternoon given morning data; if market not yet open, base on yesterday/history)"
    )
    likely_tom_rise_desc: Optional[str] = Field(
        None, description="Reasoning for a potential price rise tomorrow"
    )
    likely_short_term_rise_desc: Optional[str] = Field(
        None, description="Reasoning for a potential rise in the next 1-2 weeks"
    )
    likely_long_term_rise_desc: Optional[str] = Field(
        None, description="Reasoning for a potential rise over 6+ months"
    )
