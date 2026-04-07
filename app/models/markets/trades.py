"""Trade OHLCV bars and derived technical aggregates (fin_markets schema)."""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class SecurityTradeRecord(BaseModel):
    """Pydantic model for fin_markets.security_trades rows (OHLCV bars)."""

    id: Optional[int] = None
    security_id: int
    trade_date: date
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    interval: str = "1d"
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Optional[int] = None
    trade_count: Optional[int] = None
    currency: str = "USD"

    model_config = {"from_attributes": True}


class TradeStatAggregRecord(BaseModel):
    """Pydantic model for fin_markets.security_trade_stat_aggregs rows.

    Pre-computed technical indicators per OHLCV bar.
    """

    id: Optional[int] = None
    security_id: int
    published_at: datetime
    currency: Optional[str] = None

    # Price
    price: Optional[Decimal] = None
    interval_return: Optional[Decimal] = None

    # Lags & streaks
    return_1d_lag: Optional[Decimal] = None
    return_2d_lag: Optional[Decimal] = None
    return_3d_lag: Optional[Decimal] = None
    consecutive_up_days: Optional[int] = None
    consecutive_down_days: Optional[int] = None

    # SMAs
    sma_3: Optional[Decimal] = None
    sma_7: Optional[Decimal] = None
    sma_10: Optional[Decimal] = None
    sma_20: Optional[Decimal] = None
    sma_50: Optional[Decimal] = None
    sma_200: Optional[Decimal] = None

    # EMAs
    ema_12: Optional[Decimal] = None
    ema_26: Optional[Decimal] = None

    # MACD
    macd_signal: Optional[Decimal] = None

    # Momentum / oscillators
    rsi_6: Optional[Decimal] = None
    rsi_14: Optional[Decimal] = None
    stoch_k: Optional[Decimal] = None
    stoch_d: Optional[Decimal] = None
    adx_14: Optional[Decimal] = None

    # Volatility
    atr_14: Optional[Decimal] = None
    bollinger_std: Optional[Decimal] = None
    volatility_20d: Optional[Decimal] = None
    volatility_60d: Optional[Decimal] = None

    # Volume
    volume_ratio: Optional[Decimal] = None
    obv: Optional[int] = None

    # Misc
    psar: Optional[Decimal] = None
    ichimoku_tenkan: Optional[Decimal] = None
    ichimoku_kijun: Optional[Decimal] = None
    price_52w_high: Optional[Decimal] = None
    price_52w_low: Optional[Decimal] = None

    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class IntradayMorningSummaryRecord(BaseModel):
    """Pydantic model for fin_markets.security_intraday_morning_summary."""

    id: Optional[int] = None
    security_id: int
    published_at: datetime

    open_price: Optional[Decimal] = None
    morning_high: Optional[Decimal] = None
    morning_low: Optional[Decimal] = None
    morning_close: Optional[Decimal] = None
    gap_percent: Optional[Decimal] = None
    gap_percent_1d_lag: Optional[Decimal] = None
    gap_percent_2d_lag: Optional[Decimal] = None
    gap_percent_3d_lag: Optional[Decimal] = None
    morning_volume: Optional[Decimal] = None
    morning_vwap: Optional[Decimal] = None
    open_30m_vol_ratio: Optional[Decimal] = None

    model_config = {"from_attributes": True}


class IntradayAfternoonSummaryRecord(BaseModel):
    """Pydantic model for fin_markets.security_intraday_afternoon_summary."""

    id: Optional[int] = None
    security_id: int
    published_at: datetime

    afternoon_open: Optional[Decimal] = None
    afternoon_high: Optional[Decimal] = None
    afternoon_low: Optional[Decimal] = None
    close_price: Optional[Decimal] = None
    afternoon_volume: Optional[Decimal] = None
    afternoon_vwap: Optional[Decimal] = None
    tail_30m_vol_ratio: Optional[Decimal] = None
    tail_30m_return: Optional[Decimal] = None
    tail_30m_return_1d_lag: Optional[Decimal] = None
    tail_30m_return_2d_lag: Optional[Decimal] = None
    tail_30m_return_3d_lag: Optional[Decimal] = None

    model_config = {"from_attributes": True}
