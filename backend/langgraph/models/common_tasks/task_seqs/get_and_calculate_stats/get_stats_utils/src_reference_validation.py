"""src_reference_validation — cross-check that injected data originates from a known task output.

When ``get_stats`` receives data via direct injection (``text_content`` or
``json_input``) instead of fetching from an external provider, callers may
supply a ``src_task_id`` that identifies the upstream task that produced the
data.  This module loads that task's output from ``fin_agents.task_executions``
and validates that the injected payload contains values that can be traced back
to the source output — providing a lightweight data-provenance check.

Validation strategy
-------------------
``text_content`` path:
    The injected text is expected to be a substring of the source task's
    string leaf values (collected raw, without JSON serialisation so that
    newlines and unicode are preserved verbatim).  A
    ``_TEXT_MATCH_PREFIX_LEN``-character prefix is used so that downstream
    trimming of very long documents still passes.

``json_input`` path:
    All **string** leaf values are collected from ``json_input`` (numbers and
    booleans are skipped because they are ambiguous in floating-point
    representations).  If there are more than :data:`_SAMPLE_THRESHOLD` such
    values, :data:`_SAMPLE_SIZE` are drawn uniformly at random without
    replacement.  Each sample is then substring-searched in the raw string
    corpus of the source output (joined leaf values, not JSON-serialised).
    At least :data:`_MIN_MATCH_RATIO` of sampled values must be found; if none
    are found the check hard-fails with
    :data:`~backend.langgraph.models.common_tasks.errors.codes.STATS_TASK_SRC_REF_MISMATCH`.

Public exports
--------------
``validate_src_reference`` — async entry point called from ``get_stats._handler``.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_SRC_REF_MISMATCH,
    STATS_TASK_SRC_REF_MISSING,
)

logger = logging.getLogger(__name__)

# When more than this many string leaf values exist in json_input, sample instead.
_SAMPLE_THRESHOLD: int = 100
# Number of values to sample when threshold is exceeded.
_SAMPLE_SIZE: int = 20
# Prefix length used for text_content substring check.
_TEXT_MATCH_PREFIX_LEN: int = 200
# Minimum ratio of sampled string values that must appear in src output.
_MIN_MATCH_RATIO: float = 0.0  # 0 = any single match is sufficient; hard-fail only on 0/N


def _collect_string_leaves(obj: Any, _acc: list[str] | None = None) -> list[str]:
    """Recursively collect all string leaf values from a nested dict/list structure.

    Args:
        obj:  Any JSON-compatible value.
        _acc: Accumulator list (internal, do not pass).

    Returns:
        Flat list of string values found at every leaf of *obj*.
    """
    if _acc is None:
        _acc = []
    if isinstance(obj, str):
        stripped = obj.strip()
        if stripped:
            _acc.append(stripped)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_string_leaves(v, _acc)
    elif isinstance(obj, list):
        for item in obj:
            _collect_string_leaves(item, _acc)
    return _acc


async def _load_src_output(src_task_id: str) -> dict:
    """Fetch the most recent task execution output for *src_task_id* from DB.

    Reads from the replica first; falls back to primary when the row is absent
    (replication lag on very recent tasks).

    Args:
        src_task_id: UUID of the upstream source task.

    Returns:
        Parsed output dict from ``fin_agents.task_executions``.

    Raises:
        ValueError: When no output row is found for the given task_id.
    """
    _SQL = (
        "SELECT output FROM fin_agents.task_executions "
        "WHERE task_id = %s ORDER BY retry_num DESC LIMIT 1"
    )
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_SQL, (src_task_id,))
        row = await cur.fetchone()

    if row is None:
        # Possible replication lag — retry on primary.
        async with raw_conn(readonly=False) as conn:
            cur = await conn.execute(_SQL, (src_task_id,))
            row = await cur.fetchone()

    if row is None:
        raise ValueError(
            f"[{STATS_TASK_SRC_REF_MISSING}] No task_executions row found for "
            f"src_task_id={src_task_id!r}. "
            f"Ensure the source task has completed before injecting its output."
        )
    return row["output"] or {}


async def validate_src_reference(
    src_task_id: str,
    *,
    injected_text: str | None = None,
    injected_json: dict | None = None,
) -> None:
    """Validate that injected data references values present in the source task's output.

    Exactly one of *injected_text* or *injected_json* must be supplied.

    For the ``text_content`` path: confirms the first
    :data:`_TEXT_MATCH_PREFIX_LEN` characters of the injected text appear
    within the serialised source output.

    For the ``json_input`` path: samples string leaf values from the injected
    dict and checks that at least one appears in the serialised source output.
    Raises hard on zero matches; logs a warning on partial matches below
    :data:`_MIN_MATCH_RATIO`.

    Args:
        src_task_id:    ``task_id`` of the upstream source task.
        injected_text:  Text content injected via ``GetStatsInput.text_content``.
        injected_json:  Structured dict injected via ``GetStatsInput.json_input``.

    Raises:
        ValueError: When the src task output is absent or no injected values
                    match the source output.
    """
    src_output = await _load_src_output(src_task_id)
    # Use raw string leaf corpus to avoid json-encoding artefacts (e.g. \n → \\n)
    # that would cause legitimate substrings to fail substring-search.
    src_corpus = "\n".join(_collect_string_leaves(src_output))

    if injected_text is not None:
        prefix = injected_text[:_TEXT_MATCH_PREFIX_LEN]
        if prefix and prefix not in src_corpus:
            raise ValueError(
                f"[{STATS_TASK_SRC_REF_MISMATCH}] text_content prefix not found in "
                f"src_task_id={src_task_id!r} output. "
                f"Prefix checked ({len(prefix)} chars): {prefix[:80]!r}. "
                f"Source corpus starts with: {src_corpus[:80]!r}."
            )
        return

    if injected_json is not None:
        leaves = _collect_string_leaves(injected_json)
        if not leaves:
            # No string values to validate — skip check.
            return

        sample: list[str]
        if len(leaves) > _SAMPLE_THRESHOLD:
            sample = random.sample(leaves, min(_SAMPLE_SIZE, len(leaves)))
        else:
            sample = leaves

        matches = sum(1 for v in sample if v in src_corpus)
        if matches == 0:
            failing = [v[:60] for v in sample if v not in src_corpus]
            raise ValueError(
                f"[{STATS_TASK_SRC_REF_MISMATCH}] 0/{len(sample)} sampled json_input string "
                f"values found in src_task_id={src_task_id!r} output. "
                f"Sampled values checked: {failing[:5]!r}. "
                f"Source corpus starts with: {src_corpus[:100]!r}."
            )
        match_ratio = matches / len(sample)
        if match_ratio < _MIN_MATCH_RATIO:
            failing = [v[:60] for v in sample if v not in src_corpus]
            logger.error(
                "[%s] Only %d/%d (%.0f%%) sampled json_input values found in src_task_id=%r output. "
                "Unmatched values: %r. Source corpus snippet: %r.",
                STATS_TASK_SRC_REF_MISMATCH, matches, len(sample), match_ratio * 100, src_task_id,
                failing[:3], src_corpus[:100],
            )


__all__ = ["validate_src_reference"]
