"""Macroeconomic data, industry stats, and cross-asset dynamics (fin_markets schema)."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import SentimentLevel


class MacroEconomicsRecord(BaseModel):
    """Pydantic model for fin_markets.macro_economics rows."""

    id: Optional[int] = None
    news_ext_id: Optional[int] = None
    published_at: datetime
    category: Optional[str] = None
    industry: Optional[str] = None
    region: str
    actual: Optional[Decimal] = None
    sentiment_level: Optional[SentimentLevel] = None
    currency: Optional[str] = None
    indicator_name: Optional[str] = None
    reference_period: Optional[str] = None
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class IndustryStatRecord(BaseModel):
    """Pydantic model for fin_markets.industry_stats rows."""

    id: Optional[int] = None
    industry: Optional[str] = None
    region: Optional[str] = None
    published_at: datetime
    volume: Optional[Decimal] = None
    relative_flow_pct: Optional[Decimal] = None
    breadth_pct: Optional[Decimal] = None
    sentiment_level: Optional[SentimentLevel] = None
    currency: Optional[str] = None
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class IndustryStatAggregRecord(BaseModel):
    """Pydantic model for fin_markets.industry_stat_aggregs."""

    id: Optional[int] = None
    industry_stat_id: int
    published_at: datetime
    avg_return: Optional[Decimal] = None
    avg_return_1d_lag: Optional[Decimal] = None
    avg_return_2d_lag: Optional[Decimal] = None
    avg_return_3d_lag: Optional[Decimal] = None
    consecutive_up_days: Optional[int] = None
    consecutive_down_days: Optional[int] = None
    avg_pe: Optional[Decimal] = None
    pct_above_sma_200: Optional[Decimal] = None
    volatility_20d: Optional[Decimal] = None
    sentiment_level: Optional[SentimentLevel] = None

    model_config = {"from_attributes": True}


class IndexStatRecord(BaseModel):
    """Pydantic model for fin_markets.index_stats."""

    id: Optional[int] = None
    index_id: int
    published_at: datetime
    base_value: Optional[Decimal] = None
    news_id: Optional[int] = None
    currency: Optional[str] = None
    total_market_cap: Optional[Decimal] = None
    top10_weight: Optional[Decimal] = None
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class IndexStatAggregRecord(BaseModel):
    """Pydantic model for fin_markets.index_stat_aggregs."""

    id: Optional[int] = None
    index_stat_id: int
    published_at: datetime
    weighted_return: Optional[Decimal] = None
    weighted_return_1d_lag: Optional[Decimal] = None
    weighted_return_2d_lag: Optional[Decimal] = None
    weighted_return_3d_lag: Optional[Decimal] = None
    consecutive_up_days: Optional[int] = None
    consecutive_down_days: Optional[int] = None
    pct_above_sma_200: Optional[Decimal] = None
    avg_pe: Optional[Decimal] = None
    index_volatility_20: Optional[Decimal] = None

    model_config = {"from_attributes": True}
