"""LLM layer error code registry.

Error code prefixes
-------------------
``LLM_``       — LLM factory / provider configuration errors.
``LLM_EMBED_`` — Embedding provider configuration and response errors.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

# ── LLM factory ───────────────────────────────────────────────────────────────

#: The configured LLM_PROVIDER value is not in the supported set.
LLM_UNKNOWN_PROVIDER = "LLM_UNKNOWN_PROVIDER"

#: The selected LLM provider is recognised but not fully configured (missing key/path).
LLM_PROVIDER_NOT_CONFIGURED = "LLM_PROVIDER_NOT_CONFIGURED"

# ── Embedding provider ────────────────────────────────────────────────────────

#: The configured EMBEDDING_PROVIDER value is not in the supported set.
LLM_EMBED_UNKNOWN_PROVIDER = "LLM_EMBED_UNKNOWN_PROVIDER"

#: The embedding provider returned an empty or null embedding list.
LLM_EMBED_EMPTY_RESPONSE = "LLM_EMBED_EMPTY_RESPONSE"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each LLM layer error code to a human-readable description.
LLM_LAYER_ERRORS: dict[str, str] = {
    LLM_UNKNOWN_PROVIDER: (
        "The LLM_PROVIDER value is not recognised. "
        "Check .env for a supported provider name."
    ),
    LLM_PROVIDER_NOT_CONFIGURED: (
        "The selected LLM provider is not fully configured. "
        "Verify the required API key or model path in .env."
    ),
    LLM_EMBED_UNKNOWN_PROVIDER: (
        "The EMBEDDING_PROVIDER value is not recognised. "
        "Check .env for a supported embedding provider name."
    ),
    LLM_EMBED_EMPTY_RESPONSE: (
        "The embedding provider returned an empty response. "
        "Verify the embedding model is loaded and the provider is reachable."
    ),
}
