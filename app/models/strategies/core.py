"""Core strategy models — strategy registry, judgement history, benchmark (fin_strategies schema)."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import SentimentLevel, ConfidenceLevel


class StrategyRecord(BaseModel):
    """Pydantic model for fin_strategies.strategies (named strategy registry)."""

    id: Optional[int] = None
    name: str
    version: str = "1.0"
    description: Optional[str] = None
    is_active: bool = True
    config: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class JudgementHistoryRecord(BaseModel):
    """Pydantic model for fin_strategies.judgement_history.

    Captures per-horizon sentiment + confidence outlook for a security.
    """

    id: Optional[int] = None
    strategy_id: Optional[int] = None
    timestamp: datetime
    security_id: int
    rationale: Optional[str] = None
    extra: Optional[dict] = None

    # Per-horizon outlook
    next_day_sentiment: Optional[SentimentLevel] = None
    next_day_confidence: Optional[ConfidenceLevel] = None
    one_week_sentiment: Optional[SentimentLevel] = None
    one_week_confidence: Optional[ConfidenceLevel] = None
    one_month_sentiment: Optional[SentimentLevel] = None
    one_month_confidence: Optional[ConfidenceLevel] = None
    one_quarter_sentiment: Optional[SentimentLevel] = None
    one_quarter_confidence: Optional[ConfidenceLevel] = None
    half_year_sentiment: Optional[SentimentLevel] = None
    half_year_confidence: Optional[ConfidenceLevel] = None
    one_year_sentiment: Optional[SentimentLevel] = None
    one_year_confidence: Optional[ConfidenceLevel] = None

    model_config = {"from_attributes": True}


class JudgementBenchmarkRecord(BaseModel):
    """Pydantic model for fin_strategies.judgement_benchmark.

    Actual market performance per horizon for back-testing.
    """

    id: Optional[int] = None
    judgement_history_id: int
    security_id: int
    reference_price: Decimal
    reference_timestamp: datetime

    next_day_price: Optional[Decimal] = None
    next_day_return: Optional[Decimal] = None
    next_day_sentiment: Optional[SentimentLevel] = None

    one_week_price: Optional[Decimal] = None
    one_week_return: Optional[Decimal] = None
    one_week_sentiment: Optional[SentimentLevel] = None

    one_month_price: Optional[Decimal] = None
    one_month_return: Optional[Decimal] = None
    one_month_sentiment: Optional[SentimentLevel] = None

    one_quarter_price: Optional[Decimal] = None
    one_quarter_return: Optional[Decimal] = None
    one_quarter_sentiment: Optional[SentimentLevel] = None

    half_year_price: Optional[Decimal] = None
    half_year_return: Optional[Decimal] = None
    half_year_sentiment: Optional[SentimentLevel] = None

    one_year_price: Optional[Decimal] = None
    one_year_return: Optional[Decimal] = None
    one_year_sentiment: Optional[SentimentLevel] = None

    model_config = {"from_attributes": True}
