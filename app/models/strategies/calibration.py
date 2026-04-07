"""Sentiment scale calibration — maps numeric returns to sentiment levels (fin_strategies schema)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import SentimentLevel


class SentimentScaleCalibrationRecord(BaseModel):
    """Pydantic model for fin_strategies.sentiment_scale_calibration.

    Stores distribution stats for a security+horizon pair used to map
    projected returns → sentiment_level via quantile bands.
    """

    id: Optional[int] = None
    security_id: int
    horizon: str  # '1d', '1w', '1m', '3m', '6m', '1y'
    lookback_days: int = 730
    from_date: date
    to_date: date
    sample_count: int
    max_rise: Decimal
    max_drop: Decimal
    mean_return: Decimal
    std_return: Decimal
    computed_at: Optional[datetime] = None
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class SentimentNumericBandRecord(BaseModel):
    """Pydantic model for fin_strategies.sentiment_numeric_bands.

    Per-calibration return-band boundaries for each sentiment_level.
    """

    id: Optional[int] = None
    calibration_id: int
    sentiment_level: SentimentLevel
    lower_bound: Decimal
    upper_bound: Optional[Decimal] = None  # NULL for VERY_POSITIVE (unbounded above)
    midpoint: Decimal

    model_config = {"from_attributes": True}
