"""mock — LLM provider sub-package for non-production testing.

Sub-modules
-----------
streaming — :class:`MockChatModel` for streaming performance / load testing.
e2e       — :class:`E2EMockChatModel` for deterministic E2E test runs.
fixtures  — shared fixture constants (``E2E_TRIGGER``, ``E2E_QUERY_RESPONSE``).
"""

from backend.llm.providers.mock.e2e import E2EMockChatModel, get_e2e_mock_llm
from backend.llm.providers.mock.streaming import MockChatModel, get_mock_llm

__all__ = [
    "MockChatModel",
    "get_mock_llm",
    "E2EMockChatModel",
    "get_e2e_mock_llm",
]
