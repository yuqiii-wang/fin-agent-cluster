"""Startup validation for configured LLM and embedding providers.

Called once from the FastAPI lifespan.  Raises on misconfiguration so the
process exits immediately rather than silently continuing with a broken provider.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def validate_providers() -> None:
    """Attempt to instantiate the configured LLM and embedding providers.

    Raises:
        ValueError: When a required API key or URL is missing.
        RuntimeError: When the provider name is unrecognised.
    """
    from backend.config import get_settings
    from _shared.llm.factory import get_embedder, get_llm

    settings = get_settings()
    llm_provider = (settings.LLM_PROVIDER or "mock").strip().lower()
    emb_provider = (settings.EMBEDDING_PROVIDER or "mock").strip().lower()

    # Instantiate (does not make a network call — just validates config).
    get_llm(provider=llm_provider, streaming=False)  # type: ignore[arg-type]
    get_embedder(provider=emb_provider)  # type: ignore[arg-type]


def ping_llm() -> None:
    """Send a minimal "Hello" message to the configured LLM provider and log the result.

    Used by run.py at startup to verify the LLM endpoint is reachable before
    accepting client traffic.  Errors are logged but never raised — a ping
    failure must not prevent process startup.

    Skipped when ``LLM_PROVIDER`` is ``mock`` (no network endpoint exists).
    """
    from backend.config import get_settings
    from _shared.llm.factory import get_llm
    from langchain_core.messages import HumanMessage

    settings = get_settings()
    provider = (settings.LLM_PROVIDER or "mock").strip().lower()

    if provider == "mock":
        print("[llm_ping] provider=mock — skipping network ping")
        return

    print(f"[llm_ping] pinging provider={provider} ...")
    try:
        llm = get_llm(streaming=False)
        response = llm.invoke([HumanMessage(content="Hello")])
        content = getattr(response, "content", str(response))
        snippet = str(content)[:120].replace("\n", " ")
        print(f"[llm_ping] provider={provider} OK — {snippet}")
    except Exception as exc:  # noqa: BLE001
        logger.error("[llm_ping] provider=%s ping failed (non-fatal): %s", provider, exc)


__all__ = ["validate_providers", "ping_llm"]
