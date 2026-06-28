"""common_tasks -- shared LangGraph NodeTasks usable across multiple nodes.

Tasks
-----
``get_stats``                   -- fetch OHLCV stats from a stats provider, cache in input_raw.
``calculate_stats``             -- compute technical indicators from a StatsRecord, upsert to quant_stats.
``calculate_corr``              -- compute pairwise Pearson correlation of close prices from quant_stats.
``run_sandbox``                 -- execute LLM-generated Python or bash inside an isolated sandbox.
``dummy_task``                  -- placeholder task that ticks until a parent signal.

HANDLERS registry
-----------------
Flat dict mapping task_name -> async handler function, consumed by the Celery
completion worker (``completion_task.run_completion``).  Import and merge into
``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
    get_stats,
    GetStatsInput,
    GetStatsOutput,
    HANDLERS as _GS_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats import (
    calculate_stats,
    CalculateStatsInput,
    CalculateStatsOutput,
    HANDLERS as _CS_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_option_stats import (
    calculate_option_stats,
    CalculateOptionStatsInput,
    CalculateOptionStatsOutput,
    parse_contract_name,
    HANDLERS as _COS_HANDLERS,
)
from backend.langgraph.models.common_tasks.calculate_corr import (
    calculate_corr,
    CalculateCorrInput,
    CalculateCorrOutput,
    HANDLERS as _CC_HANDLERS,
)
from backend.langgraph.models.common_tasks.dummy_task import (
    dummy_task,
    DummyTaskInput,
    DummyTaskOutput,
    HANDLERS as _DT_HANDLERS,
)
from backend.langgraph.models.common_tasks.run_sandbox import (
    run_sandbox,
    RunSandboxInput,
    RunSandboxOutput,
    HANDLERS as _SB_HANDLERS,
)

HANDLERS: dict = {
    **_GS_HANDLERS,
    **_CS_HANDLERS,
    **_COS_HANDLERS,
    **_CC_HANDLERS,
    **_DT_HANDLERS,
    **_SB_HANDLERS,
}
STREAM_PROMPT_BUILDERS: dict = {}

__all__ = [
    "get_stats",
    "GetStatsInput",
    "GetStatsOutput",
    "calculate_stats",
    "CalculateStatsInput",
    "CalculateStatsOutput",
    "calculate_option_stats",
    "CalculateOptionStatsInput",
    "CalculateOptionStatsOutput",
    "parse_contract_name",
    "calculate_corr",
    "CalculateCorrInput",
    "CalculateCorrOutput",
    "dummy_task",
    "DummyTaskInput",
    "DummyTaskOutput",
    "run_sandbox",
    "RunSandboxInput",
    "RunSandboxOutput",
    "HANDLERS",
    "STREAM_PROMPT_BUILDERS",
]
