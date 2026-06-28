
from enum import Enum


class STATS_DATA_TYPE(Enum):
    OHLCV = "ohlcv"
    OPTIONS = "options"
    FUTURES = "futures"
    TEXT = "text"
    FUNDAMENTALS = "fundamentals"


class STATS_VIEW_TYPE(Enum):
    DATA_FRAME = 'DataFrame'
    CANDLE_STICK = 'CandleStick'
    STACK_CANDLE_STICK = 'StackCandleStick'
    LINE_CHART = 'LineChart'
    BAR_CHART = 'BarChart'
    PIE_CHART = 'PieChart'
    OPTIONS_VOLATILITY_SMILE = 'OptionsVolatilitySmile'


class OPTIONS_PERIODS(Enum):
    NEXT = ('next', 0)
    ONE_WEEK = ('one week', 3600 * 24 * 7)
    ONE_MONTH = ('one month', 3600 * 24 * 30)
    ONE_QUARTER = ('one quarter', 3600 * 24 * 90)
    HALF_YEAR = ('half year', 3600 * 24 * 180)
    ONE_YEAR = ('one year', 3600 * 24 * 365)

    def __new__(cls, *args):
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            display_name, seconds = args[0]
        elif len(args) == 2:
            display_name, seconds = args
        else:
            raise ValueError(f"Invalid arguments for {cls.__name__}: {args}")
        obj = object.__new__(cls)
        obj._value_ = (display_name, seconds)
        return obj

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, (tuple, list)) and len(value) == 2:
            for member in cls:
                if member.value == tuple(value):
                    return member
        raise ValueError(f'Invalid {cls.__name__}: {value}')

    @classmethod
    def from_tuple(cls, v):
        if isinstance(v, cls):
            return v
        return cls(v)

    @property
    def display_name(self) -> str:
        return self.value[0]
    
    @property
    def seconds(self) -> int:
        return self.value[1]

class FUTURES_PERIODS(Enum):
    ONE_MONTH = ('one month', 3600 * 24 * 30)
    ONE_QUARTER = ('one quarter', 3600 * 24 * 90)
    HALF_YEAR = ('half year', 3600 * 24 * 180)
    ONE_YEAR = ('one year', 3600 * 24 * 365)
    
    def __new__(cls, *args):
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            display_name, seconds = args[0]
        elif len(args) == 2:
            display_name, seconds = args
        else:
            raise ValueError(f"Invalid arguments for {cls.__name__}: {args}")
        obj = object.__new__(cls)
        obj._value_ = (display_name, seconds)
        return obj

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, (tuple, list)) and len(value) == 2:
            for member in cls:
                if member.value == tuple(value):
                    return member
        raise ValueError(f'Invalid {cls.__name__}: {value}')

    @classmethod
    def from_tuple(cls, v):
        if isinstance(v, cls):
            return v
        return cls(v)

    @property
    def display_name(self) -> str:
        return self.value[0]
    
    @property
    def seconds(self) -> int:
        return self.value[1]