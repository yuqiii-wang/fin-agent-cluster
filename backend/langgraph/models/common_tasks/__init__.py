"""common_tasks — shared LangGraph NodeTasks usable across multiple nodes.

Tasks
-----
``get_stats``       — fetch OHLCV stats + news from the resource API, cache in quant_raw.
``calculate_stats`` — compute technical indicators from a StatsRecord, upsert to quant_stats.
``calculate_corr``  — compute pairwise Pearson correlation of close prices from quant_stats.

HANDLERS registry
-----------------
Flat dict mapping task_name → async handler function, consumed by the Celery
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
from backend.langgraph.models.common_tasks.calculate_corr import (
    calculate_corr,
    CalculateCorrInput,
    CalculateCorrOutput,
    HANDLERS as _CC_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news import (
    get_news,
    GetNewsInput,
    GetNewsOutput,
    digest_news,
    DigestNewsInput,
    DigestNewsOutput,
    get_and_digest_news,
    GetAndDigestNewsInput,
    GetAndDigestNewsOutput,
    HANDLERS as _GDN_HANDLERS,
    STREAM_PROMPT_BUILDERS as _GDN_SPB,
)

HANDLERS: dict = {**_GS_HANDLERS, **_CS_HANDLERS, **_CC_HANDLERS, **_GDN_HANDLERS}
STREAM_PROMPT_BUILDERS: dict = {**_GDN_SPB}

__all__ = [
    "get_stats",
    "GetStatsInput",
    "GetStatsOutput",
    "calculate_stats",
    "CalculateStatsInput",
    "CalculateStatsOutput",
    "calculate_corr",
    "CalculateCorrInput",
    "CalculateCorrOutput",
    "get_news",
    "GetNewsInput",
    "GetNewsOutput",
    "digest_news",
    "DigestNewsInput",
    "DigestNewsOutput",
    "get_and_digest_news",
    "GetAndDigestNewsInput",
    "GetAndDigestNewsOutput",
    "HANDLERS",
    "STREAM_PROMPT_BUILDERS",
]
