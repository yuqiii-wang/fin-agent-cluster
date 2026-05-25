"""Startup validation for configured LLM and embedding providers.

Called once from the FastAPI lifespan.  Raises on misconfiguration so the
process exits immediately rather than silently continuing with a broken provider.
"""

from __future__ import annotations


def validate_providers() -> None:
    """Attempt to instantiate the configured LLM and embedding providers.

    Raises:
        ValueError: When a required API key or URL is missing.
        RuntimeError: When the provider name is unrecognised.
    """
    from backend.config import get_settings
    from backend.llm.factory import get_completion_llm, get_embedder

    settings = get_settings()
    llm_provider = (settings.LLM_PROVIDER or "mock").strip().lower()
    emb_provider = (settings.EMBEDDING_PROVIDER or "mock").strip().lower()

    # Instantiate (does not make a network call — just validates config).
    get_completion_llm(provider=llm_provider)  # type: ignore[arg-type]
    get_embedder(provider=emb_provider)  # type: ignore[arg-type]


__all__ = ["validate_providers"]
