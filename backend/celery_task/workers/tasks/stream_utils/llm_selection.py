"""LLM instance selection for streaming Celery tasks."""

from __future__ import annotations

from typing import Any


def select_llm(query: str, llm: str = "ollama") -> Any:
    """Select LLM based on query prefix.

    Returns a ``MockLLM`` (with optional rate/duration overrides) when the
    query starts with ``"semantic test"`` or ``"concurrency test"``, so
    load-testing flows never reach the real Ollama endpoint.  All other
    queries use ``OllamaLLM``.

    Args:
        query: Raw user query string from the task payload.

    Returns:
        A ``BaseChatModel`` instance whose ``.provider`` and ``.model``
        attributes carry metadata for DB storage.
    """
    import re
    from backend.llm.factory import get_llm
    from backend.llm.providers.mock_llm import get_mock_llm
    from backend.llm.providers.mock_llm.word_pool import SEMANTIC_DURATION_SECS, SEMANTIC_TOKENS_PER_SEC

    if query.startswith("semantic test") or query.startswith("concurrency test"):
        _tps_m = re.search(r"\btps=(\d+(?:\.\d+)?)", query)
        _dur_m = re.search(r"\bdur=(\d+(?:\.\d+)?)", query)
        _tps = float(_tps_m.group(1)) if _tps_m else SEMANTIC_TOKENS_PER_SEC
        _dur = float(_dur_m.group(1)) if _dur_m else float(SEMANTIC_DURATION_SECS)
        return get_mock_llm(tokens_per_sec=_tps, duration_secs=_dur)
    return get_llm(llm)
