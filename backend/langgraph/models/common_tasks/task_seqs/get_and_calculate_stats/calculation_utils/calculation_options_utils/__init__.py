"""calculation_options_utils — options stats calculation sub-package.

Splits calculate_option_stats into focused modules:
- models:  Pydantic input/output models.
- parsers: OSI contract name parsing and value coercion helpers.
- handler: Celery-layer DB persistence handler.
- task:    LangGraph @task orchestration and NodeTask registration.
"""

from .handler import _handler, calculate_option_stats_handler
from .models import (
    CalculateOptionStatsInput,
    CalculateOptionStatsOutput,
    OptionContractInput,
    VolSmileExpiry,
    VolSmilePoint,
)
from .parsers import parse_contract_name
from .task import HANDLERS, calculate_option_stats

__all__ = [
    "OptionContractInput",
    "CalculateOptionStatsInput",
    "VolSmilePoint",
    "VolSmileExpiry",
    "CalculateOptionStatsOutput",
    "parse_contract_name",
    "calculate_option_stats_handler",
    "_handler",
    "calculate_option_stats",
    "HANDLERS",
]
