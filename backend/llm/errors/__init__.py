"""LLM error code registry.

Error code prefixes
-------------------
``LLM_``  — LLM inference and streaming failures.
"""

from __future__ import annotations

#: The LLM response did not contain valid JSON after all retry attempts.
LLM_JSON_INVALID = "LLM_JSON_INVALID"

#: The LLM stream was permanently lost (e.g. connection dropped, all retries exhausted).
LLM_STREAM_LOST = "LLM_STREAM_LOST"

__all__ = [
    "LLM_JSON_INVALID",
    "LLM_STREAM_LOST",
]
