"""backend.celery_task.workers.tasks.stream_utils -- helpers for the streaming Celery tasks.

Modules
-------
text_utils       -- extract_thinking_answer, extract_json_from_text
llm_selection    -- select_llm
prompt_registry  -- STREAM_PROMPT_BUILDERS, get_stream_prompt_builders
stream_core      -- run_stream_core, BATCH_MAX_SIZE, BATCH_FLUSH_MS
prompt_builder   -- run_stream_async (stream_llm / conclusion-node path)
compact_continue -- detect_and_compress_repetition, run_stream_compact_continue_async
"""

from __future__ import annotations

from .compact_continue import detect_and_compress_repetition, run_stream_compact_continue_async
from .llm_selection import select_llm
from .prompt_builder import run_stream_async
from .prompt_registry import STREAM_PROMPT_BUILDERS, get_stream_prompt_builders
from .stream_core import BATCH_FLUSH_MS, BATCH_MAX_SIZE, run_stream_core
from .text_utils import extract_json_from_text, extract_thinking_answer

__all__ = [
    "BATCH_FLUSH_MS",
    "BATCH_MAX_SIZE",
    "STREAM_PROMPT_BUILDERS",
    "detect_and_compress_repetition",
    "extract_json_from_text",
    "extract_thinking_answer",
    "get_stream_prompt_builders",
    "run_stream_async",
    "run_stream_compact_continue_async",
    "run_stream_core",
    "select_llm",
]
