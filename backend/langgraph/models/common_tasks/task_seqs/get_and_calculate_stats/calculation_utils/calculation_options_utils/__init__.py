"""calculation_options_utils -- options stats calculation sub-package.

Splits calculate_option_stats into focused modules:
- models:       Pydantic input/output models.
- parsers:      OSI contract name parsing and value coercion helpers.
- parser_utils: Additional parsing utilities for option chain data.
- handler:      Celery-layer DB persistence handler.
- task:         LangGraph @task orchestration and NodeTask registration.
"""

from .handler import _handler, calculate_option_stats_handler
from .models import (
    CalculateOptionStatsInput,
    CalculateOptionStatsOutput,
    OptionContractInput,
    PcRatioPoint,
    VolSmileExpiry,
    VolSmilePoint,
)
from .parsers import parse_contract_name
from .parser_utils import (
    extract_value,
    parse_numeric_value,
    parse_integer_value,
    parse_percent_value,
    parse_contract_name_from_link,
)
from .task import HANDLERS, calculate_option_stats

__all__ = [
    "OptionContractInput",
    "CalculateOptionStatsInput",
    "VolSmilePoint",
    "VolSmileExpiry",
    "PcRatioPoint",
    "CalculateOptionStatsOutput",
    "parse_contract_name",
    "extract_value",
    "parse_numeric_value",
    "parse_integer_value",
    "parse_percent_value",
    "parse_contract_name_from_link",
    "calculate_option_stats_handler",
    "_handler",
    "calculate_option_stats",
    "HANDLERS",
]
