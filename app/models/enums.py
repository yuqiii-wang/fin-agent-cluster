"""Shared enums mirroring PostgreSQL ENUM types across fin_markets and fin_strategies schemas."""

import enum


class SentimentLevel(str, enum.Enum):
    """7-point directional outlook scale. Used in both fin_markets and fin_strategies."""

    VERY_NEGATIVE = "VERY_NEGATIVE"
    NEGATIVE = "NEGATIVE"
    SLIGHTLY_NEGATIVE = "SLIGHTLY_NEGATIVE"
    NEUTRAL = "NEUTRAL"
    SLIGHTLY_POSITIVE = "SLIGHTLY_POSITIVE"
    POSITIVE = "POSITIVE"
    VERY_POSITIVE = "VERY_POSITIVE"


class ConfidenceLevel(str, enum.Enum):
    """Agent conviction in its own judgement. Used in fin_strategies.judgement_history."""

    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class QueryStatus(str, enum.Enum):
    """Status of a user query in fin_agents.user_queries."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TermStructure(str, enum.Enum):
    """Futures/options term structure shape."""

    CONTANGO = "CONTANGO"
    BACKWARDATION = "BACKWARDATION"
    FLAT = "FLAT"


class MacroRegime(str, enum.Enum):
    """Macro market regime."""

    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    NEUTRAL = "NEUTRAL"


class SMA200Trend(str, enum.Enum):
    """200-day SMA trend direction."""

    RISING = "RISING"
    FALLING = "FALLING"
    FLAT = "FLAT"


class VolumeTrend(str, enum.Enum):
    """Weekly volume trend direction."""

    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    FLAT = "FLAT"
