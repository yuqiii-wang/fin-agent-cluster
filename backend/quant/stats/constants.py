
from enum import Enum


class STATS_DATA_TYPE(Enum):
    OHLCV = "ohlcv"
    OPTIONS = "options"
    FUTURES = "futures"
    TEXT = "text"
    FUNDAMENTALS = "fundamentals"


OHLCV = STATS_DATA_TYPE.OHLCV
OPTIONS = STATS_DATA_TYPE.OPTIONS
FUTURES = STATS_DATA_TYPE.FUTURES
TEXT = STATS_DATA_TYPE.TEXT
FUNDAMENTALS = STATS_DATA_TYPE.FUNDAMENTALS

class STATS_VIEW_TYPE(Enum):
    DATA_FRAME = 'DataFrame'
    CANDLE_STICK = 'CandleStick'
    STACK_CANDLE_STICK = 'StackCandleStick'
    LINE_CHART = 'LineChart'
    BAR_CHART = 'BarChart'
    PIE_CHART = 'PieChart'
    OPTIONS_VOLATILITY_SMILE = 'OptionsVolatilitySmile'


