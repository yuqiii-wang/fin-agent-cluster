"""ARK (Volcano Engine / Doubao) chat model provider and its native web_search extension.

ARK exposes an OpenAI-compatible ``/chat/completions`` endpoint at
``https://ark.cn-beijing.volces.com/api/v3``.  Certain Doubao models also expose a
native ``/api/v3/web_search`` endpoint that performs a web search and summarises the
result in a single call — this is wired up via :meth:`ArkLLM.search_and_summary`.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Optional, Sequence, Union

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from backend.config import get_settings
from _shared.httpx_client import (
    ConnectError,
    TimeoutException,
    make_ark_async_client,
    make_ark_sync_client,
)
from _shared.llm.providers.base_llm import BaseLLM, SearchAndSummaryResult

logger = logging.getLogger(__name__)


def _to_openai_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Convert LangChain messages to OpenAI /chat/completions format.

    Handles tool-call assistant turns and tool result turns so the agent loop
    works correctly.

    Args:
        messages: LangChain message list.

    Returns:
        List of OpenAI-compatible message dicts.
    """
    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, SystemMessage):
            result.append({"role": "system", "content": str(msg.content)})
        elif isinstance(msg, ToolMessage):
            result.append({
                "role": "tool",
                "content": str(msg.content),
                "tool_call_id": msg.tool_call_id,
            })
        elif isinstance(msg, AIMessage):
            entry: dict[str, Any] = {
                "role": "assistant",
                "content": str(msg.content) if msg.content else "",
            }
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            result.append(entry)
        else:
            result.append({"role": "assistant", "content": str(msg.content)})
    return result


class ArkLLM(BaseLLM):
    """ARK (Volcano Engine / Doubao) chat model using plain httpx.

    Calls the ARK OpenAI-compatible ``/chat/completions`` endpoint directly
    via httpx so HTTP proxy, timeouts, and streaming are fully controlled
    without depending on ``langchain_openai``.

    Attributes:
        provider:    Always ``"ark"`` — read by stream infrastructure for DB storage.
        model:       ARK model identifier, e.g. ``"doubao-seed-2-0-mini-260428"``.
        base_url:    ARK API base URL, e.g.
                     ``"https://ark.cn-beijing.volces.com/api/v3"``.
        api_key:     ARK API key (Bearer token).
        http_proxy:  Optional HTTP proxy URL forwarded to httpx.
        temperature: Sampling temperature.
    """

    provider: str = "ark"
    model: str
    base_url: str
    api_key: str
    http_proxy: Optional[str] = None
    temperature: float = 0.1

    @property
    def _llm_type(self) -> str:
        return "ark"

    def _auth_headers(self) -> dict[str, str]:
        """Return the Authorization header dict for ARK requests."""
        return {"Authorization": f"Bearer {self.api_key}"}

    def bind_tools(
        self,
        tools: Sequence[Union[dict[str, Any], type, Any, BaseTool]],
        **kwargs: Any,
    ) -> Runnable:
        """Bind tools to this LLM so they are passed to the ARK API.

        Converts LangChain tool objects to OpenAI function-call format and
        returns a new Runnable with the tools embedded as bound kwargs.

        Args:
            tools:   LangChain tools, callables, Pydantic models, or raw dicts.
            **kwargs: Additional kwargs forwarded to :py:meth:`bind`.

        Returns:
            A :class:`Runnable` that will pass ``tools`` to ``/chat/completions``.
        """
        openai_tools = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=openai_tools, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous (non-streaming) generation via blocking httpx.

        Args:
            messages:    LangChain messages.
            stop:        Optional stop sequences.
            run_manager: LangChain callback manager (unused).
            **kwargs:    May include ``tools`` list from :py:meth:`bind_tools`.

        Returns:
            :class:`ChatResult` wrapping the full assistant message.
        """
        url = f"{self.base_url}/chat/completions"
        normalized_messages = self._normalize_messages(messages)
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai_messages(normalized_messages),
            "stream": False,
            "temperature": self.temperature,
        }
        if stop:
            request_body["stop"] = stop
        if "tools" in kwargs:
            request_body["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            request_body["tool_choice"] = kwargs["tool_choice"]

        try:
            with make_ark_sync_client(proxy=self.http_proxy, timeout_seconds=120.0) as client:
                resp = client.post(url, json=request_body, headers=self._auth_headers())
                if resp.status_code >= 400:
                    logger.error(
                        "[ArkLLM] HTTP %d from %s — Request: %s",
                        resp.status_code, url, json.dumps(request_body, ensure_ascii=False)[:5000],
                    )
                    logger.error(
                        "[ArkLLM] HTTP %d from %s — Response: %s",
                        resp.status_code, url, resp.text[:5000],
                    )
                    resp.raise_for_status()
                data = resp.json()
        except ConnectError as exc:
            logger.error("[ArkLLM] cannot connect to ARK at %s: %s", url, exc)
            raise
        except TimeoutException as exc:
            logger.error("[ArkLLM] request to %s timed out: %s", url, exc)
            raise

        choice = data["choices"][0]
        msg_data = choice.get("message", {})
        content: str = msg_data.get("content") or ""
        raw_tool_calls = msg_data.get("tool_calls") or []

        if raw_tool_calls:
            tool_calls = [
                {
                    "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    "name": tc["function"]["name"],
                    "args": json.loads(tc["function"].get("arguments", "{}")),
                    "type": "tool_call",
                }
                for tc in raw_tool_calls
            ]
            ai_msg = AIMessage(content=content, tool_calls=tool_calls)
        else:
            ai_msg = AIMessage(content=content)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Fall back to the sync path when tools are bound.

        ``_astream`` emits content tokens only; tool_calls are only present on
        the non-streaming response.  When ``tools`` is in ``kwargs``, run
        ``_generate`` in a thread pool so tool_calls propagate correctly.
        """
        import asyncio
        if "tools" in kwargs:
            return await asyncio.to_thread(
                lambda: self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            )
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Stream tokens from ARK /chat/completions using OpenAI SSE.

        Each SSE line is::

            data: {"choices": [{"delta": {"content": "..."}, "finish_reason": null}]}

        The stream ends with ``data: [DONE]``.

        Args:
            messages:    LangChain messages.
            stop:        Optional stop sequences.
            run_manager: LangChain callback manager (unused).

        Yields:
            :class:`ChatGenerationChunk` for each non-empty content delta.
        """
        url = f"{self.base_url}/chat/completions"
        normalized_messages = self._normalize_messages(messages)
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai_messages(normalized_messages),
            "stream": True,
            "temperature": self.temperature,
        }
        if stop:
            request_body["stop"] = stop
        if "tools" in kwargs:
            request_body["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            request_body["tool_choice"] = kwargs["tool_choice"]

        try:
            async with make_ark_async_client(proxy=self.http_proxy, timeout_seconds=120.0) as client:
                async with client.stream(
                    "POST", url, json=request_body, headers=self._auth_headers()
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        body_str = body.decode(errors="replace")
                        logger.error(
                            "[ArkLLM] HTTP %d from %s — Request: %s",
                            resp.status_code, url, json.dumps(request_body, ensure_ascii=False)[:500],
                        )
                        logger.error(
                            "[ArkLLM] HTTP %d from %s — Response: %s",
                            resp.status_code, url, body_str[:5000],
                        )
                        resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            logger.error("[ArkLLM] failed to parse SSE payload: %r", payload[:120])
                            continue
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        content: str = delta.get("content") or ""
                        if content:
                            try:
                                yield ChatGenerationChunk(
                                    message=AIMessageChunk(content=content)
                                )
                            except GeneratorExit:
                                return
        except ConnectError as exc:
            logger.error("[ArkLLM] cannot connect to ARK at %s: %s", url, exc)
            raise
        except TimeoutException as exc:
            logger.error("[ArkLLM] request to %s timed out: %s", url, exc)
            raise

    # ------------------------------------------------------------------
    # Native web_search support
    # ------------------------------------------------------------------

    async def search_and_summary(
        self,
        query: str,
        **kwargs: Any,
    ) -> Optional["SearchAndSummaryResult"]:
        """Call ARK/Doubao's native web-search endpoint.

        Uses the standard ``/chat/completions`` endpoint with
        ``tools=[{"type":"web_search"}]`` — Doubao models that support
        ``web_search`` run an internet search, cite sources, and return
        a summarised answer.  Models that do not support the
        ``web_search`` tool raise an HTTP error; in that case we return
        ``None`` so the caller falls back to DDGS + LLM summary.

        Args:
            query: Plain-text query.
            **kwargs: Extra request body overrides forwarded verbatim.

        Returns:
            :class:`SearchAndSummaryResult` on success, ``None`` when the
            tool is unsupported / disabled.
        """
        if not query or not query.strip():
            return None

        url = f"{self.base_url}/chat/completions"
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant with web search capability."},
                {"role": "user", "content": query},
            ],
            "tools": [
                {"type": "web_search"},
            ],
            "stream": False,
        }
        # Let callers override e.g. temperature / stream without redoing
        # the dict from scratch.
        for k, v in kwargs.items():
            request_body[k] = v

        try:
            async with make_ark_async_client(proxy=self.http_proxy, timeout_seconds=120.0) as client:
                resp = await client.post(
                    url,
                    json=request_body,
                    headers=self._auth_headers(),
                )
                if resp.status_code == 400 or resp.status_code == 403 or resp.status_code == 404:
                    # Unspecific "unsupported tool" / "feature not enabled"
                    # response — fall back to DDGS + LLM summary.
                    logger.warning(
                        "[ArkLLM.search_and_summary] HTTP %d from %s — web_search unsupported; body=%s",
                        resp.status_code, url, resp.text[:500],
                    )
                    return None
                if resp.status_code >= 400:
                    logger.error(
                        "[ArkLLM.search_and_summary] HTTP %d from %s — %s",
                        resp.status_code, url, resp.text[:500],
                    )
                    resp.raise_for_status()
                data = resp.json()
        except ConnectError as exc:
            logger.error("[ArkLLM.search_and_summary] cannot connect to ARK at %s: %s", url, exc)
            return None
        except TimeoutException as exc:
            logger.error("[ArkLLM.search_and_summary] request to %s timed out: %s", url, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — we intentionally fall back on any error
            logger.error("[ArkLLM.search_and_summary] failed: %s", exc)
            return None

        choices = data.get("choices") or []
        if not choices:
            return None

        answer_text = ""
        sources: list[dict[str, Any]] = []
        msg_data = choices[0].get("message", {})
        answer_text = msg_data.get("content") or ""

        # Doubao web_search typically puts source URLs inside tool_calls
        # or inside the assistant message itself.  Pull any URL-bearing
        # dicts out of tool_calls and the response top-level.
        raw_calls = msg_data.get("tool_calls") or []
        for tc in raw_calls:
            try:
                function_body = (tc.get("function") or {}).get("arguments") or "{}"
                if isinstance(function_body, str):
                    parsed = json.loads(function_body)
                else:
                    parsed = function_body
            except (TypeError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue
            # Normalise known shapes: {url, title, snippet} / {link, name}
            url_candidate = (
                parsed.pop("url", None) or parsed.pop("link", None) or parsed.pop("href", None)
            )
            if url_candidate:
                sources.append({
                    "url": url_candidate,
                    "title": (
                        parsed.pop("title", None) or parsed.pop("name", None) or parsed.pop("source", None) or ""
                    ),
                    "snippet": parsed.pop("snippet", None) or "",
                    **parsed,
                })

        return SearchAndSummaryResult(
            answer=answer_text,
            sources=sources,
            raw={"response": data},
        )


def get_ark_llm(temperature: float = 0.1, streaming: bool = True) -> ArkLLM:
    """Return an :class:`ArkLLM` instance configured from settings.

    The ``streaming`` parameter is accepted for API compatibility with call
    sites that pass ``streaming=False`` for structured-output invocations.
    :class:`ArkLLM` always honours ``invoke`` vs ``stream`` via the standard
    LangChain dispatch — the ``streaming`` flag here is intentionally ignored
    because :class:`BaseChatModel` dispatches correctly without it.

    Args:
        temperature: Sampling temperature; use a low value for structured output.
        streaming:   Accepted for call-site compatibility; not used internally.

    Returns:
        :class:`ArkLLM` configured from application settings.

    Raises:
        ValueError: When ``ARK_API_KEY`` is not configured.
    """
    settings = get_settings()
    if not settings.ARK_API_KEY:
        raise ValueError("ARK_API_KEY is not set; cannot initialise ARK LLM")
    return ArkLLM(
        model=settings.ARK_MODEL,
        base_url=settings.ARK_BASE_URL,
        api_key=settings.ARK_API_KEY,
        http_proxy=None,  # ARK is a domestic Chinese endpoint — always connect directly.
        temperature=temperature,
    )


__all__ = ["ArkLLM", "get_ark_llm"]
