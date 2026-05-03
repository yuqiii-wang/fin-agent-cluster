"""E2E mock LLM provider — non-streaming, deterministic responses for E2E tests.

Returns a fixed JSON payload when the query starts with :data:`E2E_TRIGGER`.
Intended for use in the ``query_node`` task during ``"DO E2E TEST NOW"`` runs.

This class is *not* registered in the LLM factory — it is instantiated directly
by :func:`~backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.workflow.run_analyze_user_query_task`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from backend.llm.providers.mock.fixtures import E2E_QUERY_RESPONSE, E2E_TRIGGER

logger = logging.getLogger(__name__)


class E2EMockChatModel(BaseChatModel):
    """Non-streaming mock LLM that returns the E2E fixture JSON.

    When any message in the conversation contains the :data:`E2E_TRIGGER` phrase
    the model returns :data:`E2E_QUERY_RESPONSE` serialised as a JSON string.
    For any other input it still returns the same fixture (safe for tests).
    """

    @property
    def _llm_type(self) -> str:
        """Return provider identifier."""
        return "e2e_mock"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Return the E2E fixture JSON as a single :class:`~langchain_core.messages.AIMessage`.

        Args:
            messages: Input messages (inspected for the trigger phrase).
            stop:     Ignored.
            **kwargs: Ignored.

        Returns:
            :class:`~langchain_core.outputs.ChatResult` wrapping the fixture JSON.
        """
        triggered = any(E2E_TRIGGER in str(m.content) for m in messages)
        if not triggered:
            logger.warning(
                "[e2e_mock] called without E2E_TRIGGER — returning fixture anyway"
            )
        content = json.dumps(E2E_QUERY_RESPONSE)
        logger.debug("[e2e_mock] returning fixture symbol=%s", E2E_QUERY_RESPONSE["symbol"])
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async passthrough to :meth:`_generate`."""
        return self._generate(messages, stop, **kwargs)


def get_e2e_mock_llm() -> E2EMockChatModel:
    """Return a ready-to-use :class:`E2EMockChatModel` instance.

    Returns:
        Configured :class:`E2EMockChatModel`.
    """
    return E2EMockChatModel()


__all__ = ["E2EMockChatModel", "get_e2e_mock_llm"]
