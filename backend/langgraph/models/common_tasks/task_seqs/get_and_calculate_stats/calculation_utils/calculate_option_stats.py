"""calculate_option_stats -- facade re-exporting from calculation_options_utils.

Implementation is split across:
  calculation_options_utils/models.py       -- Pydantic models
  calculation_options_utils/parsers.py      -- OSI parsing and coercion helpers
  calculation_options_utils/parser_utils.py -- Additional parsing utilities
  calculation_options_utils/handler.py      -- DB persistence handler
  calculation_options_utils/task.py         -- LangGraph @task and NodeTask
"""

from __future__ import annotations

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculation_options_utils import (
    HANDLERS,
    CalculateOptionStatsInput,
    CalculateOptionStatsOutput,
    OptionContractInput,
    PcRatioPoint,
    VolSmileExpiry,
    VolSmilePoint,
    _handler,
    calculate_option_stats,
    calculate_option_stats_handler,
    parse_contract_name,
    extract_value,
    parse_numeric_value,
    parse_integer_value,
    parse_percent_value,
    parse_contract_name_from_link,
)

__all__ = [
    "calculate_option_stats",
    "CalculateOptionStatsInput",
    "CalculateOptionStatsOutput",
    "OptionContractInput",
    "VolSmilePoint",
    "VolSmileExpiry",
    "PcRatioPoint",
    "parse_contract_name",
    "extract_value",
    "parse_numeric_value",
    "parse_integer_value",
    "parse_percent_value",
    "parse_contract_name_from_link",
    "calculate_option_stats_handler",
    "HANDLERS",
]
