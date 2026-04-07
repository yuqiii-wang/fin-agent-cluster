"""Strategy evaluation dimension tables A–N (fin_strategies schema).

Each dimension captures one analytical facet at evaluation time:
  A. sec_technicals        — price & derived technical signals
  B. sec_fundamentals      — slow-changing fundamentals snapshot
  C. sec_index_perf        — parent index / benchmark performance
  D. sec_industry_perf     — industry / sector aggregate performance
  E. sec_options           — options market signals
  F. sec_futures           — futures term structure
  G. sec_sector_derivatives — sector-level futures & options
  H. sec_news_sentiment    — aggregated news sentiment window
  I. sec_macro             — macro backdrop at snapshot time
  J. sec_news_topics       — news topic relevance
  K. sec_intraday          — intraday market anomaly signals
  L. sec_historical_extremes — long-term price extremes
  M. sec_digested_news     — news absorption tracking
  N. sec_weekly_trade_stats — rolling weekly stats
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import SentimentLevel, TermStructure, MacroRegime, VolumeTrend


class StrategyEvaluationContextRecord(BaseModel):
    """Pydantic model for fin_strategies.strategy_evaluation_context (header row per judgement)."""

    id: Optional[int] = None
    judgement_history_id: int
    strategy_id: int
    security_id: int
    snapshot_at: datetime
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class SecTechnicalsRecord(BaseModel):
    """Dimension A: price & derived technical signals."""

    id: Optional[int] = None
    evaluation_id: int
    trade_stat_id: Optional[int] = None
    window_coeff: Decimal = Decimal("2.0")

    macd: Optional[Decimal] = None
    macd_hist: Optional[Decimal] = None
    bollinger_upper: Optional[Decimal] = None
    bollinger_lower: Optional[Decimal] = None
    bb_pctb: Optional[Decimal] = None
    sma3: Optional[Decimal] = None
    sma5: Optional[Decimal] = None
    price_vs_sma3_pct: Optional[Decimal] = None
    price_vs_sma5_pct: Optional[Decimal] = None
    price_vs_sma50_pct: Optional[Decimal] = None
    price_vs_sma200_pct: Optional[Decimal] = None
    price_52w_pct: Optional[Decimal] = None

    model_config = {"from_attributes": True}


class SecFundamentalsRecord(BaseModel):
    """Dimension B: slow-changing fundamentals snapshot."""

    id: Optional[int] = None
    evaluation_id: int
    security_ext_id: Optional[int] = None

    market_cap_usd: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    pe_forward: Optional[Decimal] = None
    pb_ratio: Optional[Decimal] = None
    ev_ebitda: Optional[Decimal] = None
    peg_ratio: Optional[Decimal] = None
    ps_ratio: Optional[Decimal] = None
    eps_ttm: Optional[Decimal] = None
    revenue_ttm: Optional[Decimal] = None
    net_margin: Optional[Decimal] = None
    roe: Optional[Decimal] = None
    roa: Optional[Decimal] = None
    debt_to_equity: Optional[Decimal] = None
    current_ratio: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None
    short_ratio: Optional[Decimal] = None
    insider_pct: Optional[Decimal] = None
    institutional_pct: Optional[Decimal] = None
    analyst_target_price: Optional[Decimal] = None
    analyst_consensus: Optional[str] = None
    earnings_surprise_pct: Optional[Decimal] = None
    beta: Optional[Decimal] = None
    fundamental_sentiment: Optional[SentimentLevel] = None

    model_config = {"from_attributes": True}


class SecIndexPerfRecord(BaseModel):
    """Dimension C: parent index / benchmark performance."""

    id: Optional[int] = None
    evaluation_id: int
    index_security_id: Optional[int] = None
    index_stat_id: Optional[int] = None

    index_price: Optional[Decimal] = None
    index_interval_return: Optional[Decimal] = None
    index_weighted_return_5d: Optional[Decimal] = None
    index_pct_above_sma_200: Optional[Decimal] = None
    index_avg_pe: Optional[Decimal] = None
    index_volatility_20: Optional[Decimal] = None
    index_sentiment: Optional[SentimentLevel] = None

    model_config = {"from_attributes": True}


class SecNewsSentimentRecord(BaseModel):
    """Dimension H: aggregated news sentiment window."""

    id: Optional[int] = None
    evaluation_id: int
    news_latest_id: Optional[int] = None

    news_lookback_hours: int = 48
    news_article_count: Optional[int] = None
    news_positive_pct: Optional[Decimal] = None
    news_negative_pct: Optional[Decimal] = None
    news_weighted_sentiment: Optional[SentimentLevel] = None
    news_industry_sentiment: Optional[SentimentLevel] = None
    news_macro_sentiment: Optional[SentimentLevel] = None

    model_config = {"from_attributes": True}


class SecMacroRecord(BaseModel):
    """Dimension I: macro backdrop at snapshot time."""

    id: Optional[int] = None
    evaluation_id: int

    macro_vix: Optional[Decimal] = None
    macro_vix_1w_change: Optional[Decimal] = None
    macro_yield_10y: Optional[Decimal] = None
    macro_yield_2y: Optional[Decimal] = None
    macro_yield_curve: Optional[Decimal] = None
    macro_dxy: Optional[Decimal] = None
    macro_dxy_return_1d: Optional[Decimal] = None
    macro_credit_spread: Optional[Decimal] = None
    macro_regime: Optional[MacroRegime] = None

    model_config = {"from_attributes": True}


class SecIntradayRecord(BaseModel):
    """Dimension K: intraday market anomaly signals."""

    id: Optional[int] = None
    evaluation_id: int
    morning_summary_id: Optional[int] = None
    afternoon_summary_id: Optional[int] = None

    is_morning_panic: Optional[bool] = None
    is_morning_euphoria: Optional[bool] = None
    is_tail_suppression: Optional[bool] = None
    is_tail_rally: Optional[bool] = None
    is_close_manipulated: Optional[bool] = None
    intraday_momentum_score: Optional[Decimal] = None

    model_config = {"from_attributes": True}


class SecWeeklyTradeStatsRecord(BaseModel):
    """Dimension N: rolling 1-week trading statistics."""

    id: Optional[int] = None
    evaluation_id: int

    week_start: Optional[date] = None
    week_end: Optional[date] = None
    trading_days: Optional[int] = None
    week_open: Optional[Decimal] = None
    week_high: Optional[Decimal] = None
    week_low: Optional[Decimal] = None
    week_close: Optional[Decimal] = None
    week_volume: Optional[int] = None
    week_return: Optional[Decimal] = None
    week_high_return: Optional[Decimal] = None
    week_low_return: Optional[Decimal] = None
    weekly_momentum: Optional[SentimentLevel] = None
    volume_trend: Optional[VolumeTrend] = None

    model_config = {"from_attributes": True}
