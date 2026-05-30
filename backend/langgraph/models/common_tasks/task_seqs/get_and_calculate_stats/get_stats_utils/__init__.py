"""get_stats_utils — helpers for the get_stats task.

Exports
-------
``validate_json_input``     — validate structured json_input dict by data_type.
``make_cache_key``          — SHA-256 cache key builder for quant_raw lookups.
``build_provider_chain``    — resolve ordered provider fallback list for a symbol.
``PERIOD_FALLBACKS``        — period-to-fallback-periods mapping.
``MIN_BARS_FOR_CORR``       — minimum bar count for correlation calculation.
``handle_json_input``       — store structured json_input in quant_raw, return output.
``handle_text_input``       — store text_content in quant_raw, return stub output.
``handle_external_fetch``   — fetch from external providers with fallback logic.
``get_stats_pg_cache``      — quant_raw PG cache lookup for get_stats.
``validate_src_reference``  — cross-check injected data against src task output in DB.
"""

from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.cache_key import (
    make_cache_key,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.external_fetch import (
    handle_external_fetch,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.inject_handlers import (
    handle_json_input,
    handle_text_input,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.json_input_validation import (
    validate_json_input,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.pg_cache import (
    get_stats_pg_cache,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.provider_chain import (
    MIN_BARS_FOR_CORR,
    PERIOD_FALLBACKS,
    build_provider_chain,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.src_reference_validation import (
    validate_src_reference,
)

__all__ = [
    "validate_json_input",
    "make_cache_key",
    "build_provider_chain",
    "PERIOD_FALLBACKS",
    "MIN_BARS_FOR_CORR",
    "handle_json_input",
    "handle_text_input",
    "handle_external_fetch",
    "get_stats_pg_cache",
    "validate_src_reference",
]
