"""LLM layer error code registry package.

Re-exports all error code constants and the ``LLM_LAYER_ERRORS`` description dict::

    from backend.llm.errors import (
        LLM_LAYER_ERRORS,
        LLM_UNKNOWN_PROVIDER,
        LLM_PROVIDER_NOT_CONFIGURED,
        LLM_EMBED_UNKNOWN_PROVIDER,
        LLM_EMBED_EMPTY_RESPONSE,
    )
"""

from __future__ import annotations

from backend.llm.errors.codes import (
    LLM_LAYER_ERRORS,
    LLM_UNKNOWN_PROVIDER,
    LLM_PROVIDER_NOT_CONFIGURED,
    LLM_EMBED_UNKNOWN_PROVIDER,
    LLM_EMBED_EMPTY_RESPONSE,
)

__all__ = [
    "LLM_LAYER_ERRORS",
    "LLM_UNKNOWN_PROVIDER",
    "LLM_PROVIDER_NOT_CONFIGURED",
    "LLM_EMBED_UNKNOWN_PROVIDER",
    "LLM_EMBED_EMPTY_RESPONSE",
]
