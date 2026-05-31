"""calculate_option_stats — facade re-exporting from calculation_options_utils.

Implementation is split across:
  calculation_options_utils/models.py   — Pydantic models
  calculation_options_utils/parsers.py  — OSI parsing and coercion helpers
  calculation_options_utils/handler.py  — DB persistence handler
  calculation_options_utils/task.py     — LangGraph @task and NodeTask
"""

from __future__ import annotations

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculation_options_utils import (
    HANDLERS,
    CalculateOptionStatsInput,
    CalculateOptionStatsOutput,
    OptionContractInput,
    VolSmileExpiry,
    VolSmilePoint,
    _handler,
    calculate_option_stats,
    calculate_option_stats_handler,
    parse_contract_name,
)

__all__ = [
    "calculate_option_stats",
    "CalculateOptionStatsInput",
    "CalculateOptionStatsOutput",
    "OptionContractInput",
    "VolSmilePoint",
    "VolSmileExpiry",
    "parse_contract_name",
    "calculate_option_stats_handler",
    "HANDLERS",
]
