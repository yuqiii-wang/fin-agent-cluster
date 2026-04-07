"""Security fundamentals and extended aggregates (fin_markets schema)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import SentimentLevel


class SecurityExtRecord(BaseModel):
    """Pydantic model for fin_markets.security_exts (slow-changing fundamentals snapshot)."""

    id: Optional[int] = None
    security_id: int
    published_at: datetime
    currency: Optional[str] = None
    news_id: Optional[int] = None
    price: Optional[Decimal] = None
    market_cap_usd: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    pb_ratio: Optional[Decimal] = None
    net_margin: Optional[Decimal] = None
    eps_ttm: Optional[Decimal] = None
    revenue_ttm: Optional[Decimal] = None
    debt_to_equity: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None
    dividend_rate: Optional[Decimal] = None
    dividend_frequency: Optional[str] = None
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class SecurityExtAggregRecord(BaseModel):
    """Pydantic model for fin_markets.security_ext_aggregs (computed from security_exts)."""

    id: Optional[int] = None
    security_ext_id: int
    published_at: datetime
    sentiment_level: Optional[SentimentLevel] = None
    beta: Optional[Decimal] = None

    # Extended valuation
    pe_forward: Optional[Decimal] = None
    ps_ratio: Optional[Decimal] = None
    ev_ebitda: Optional[Decimal] = None
    peg_ratio: Optional[Decimal] = None
    roe: Optional[Decimal] = None
    roa: Optional[Decimal] = None
    roic: Optional[Decimal] = None
    gross_margin: Optional[Decimal] = None
    operating_margin: Optional[Decimal] = None

    # Income statement highlights
    eps_diluted: Optional[Decimal] = None
    ebitda_ttm: Optional[Decimal] = None
    net_income_ttm: Optional[Decimal] = None

    # Balance sheet
    total_debt: Optional[Decimal] = None
    total_cash: Optional[Decimal] = None
    current_ratio: Optional[Decimal] = None
    quick_ratio: Optional[Decimal] = None
    book_value_ps: Optional[Decimal] = None

    # Dividends (extended)
    payout_ratio: Optional[Decimal] = None
    ex_dividend_date: Optional[date] = None

    # Ownership
    shares_outstanding: Optional[int] = None
    float_shares: Optional[int] = None
    insider_pct: Optional[Decimal] = None
    institutional_pct: Optional[Decimal] = None
    short_interest: Optional[int] = None
    short_ratio: Optional[Decimal] = None

    # Analyst
    analyst_target_price: Optional[Decimal] = None
    analyst_count: Optional[int] = None
    earnings_surprise_pct: Optional[Decimal] = None

    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}
