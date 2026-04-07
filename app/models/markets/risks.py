"""Security-level and industry-level risk snapshots (fin_markets schema)."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import SentimentLevel


class SecurityRiskRecord(BaseModel):
    """Pydantic model for fin_markets.security_risks."""

    id: Optional[int] = None
    security_id: int
    security_ext_id: Optional[int] = None
    trade_stat_aggreg_id: Optional[int] = None
    news_id: Optional[int] = None
    published_at: datetime
    currency: Optional[str] = None
    var_95: Optional[Decimal] = None
    max_drawdown: Optional[Decimal] = None
    sentiment_level: Optional[SentimentLevel] = None
    risk_score: Optional[Decimal] = None
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class IndustryRiskRecord(BaseModel):
    """Pydantic model for fin_markets.industry_risks."""

    id: Optional[int] = None
    industry: str
    region: str
    industry_stat_id: Optional[int] = None
    news_id: Optional[int] = None
    published_at: datetime
    currency: Optional[str] = None
    var_95: Optional[Decimal] = None
    pct_high_risk: Optional[Decimal] = None
    concentration_risk: Optional[Decimal] = None
    max_drawdown: Optional[Decimal] = None
    risk_score: Optional[Decimal] = None
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}
