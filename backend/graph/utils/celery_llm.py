"""Celery LLM dispatch utility — bridges asyncio LangGraph nodes to celery-ingest.

LangGraph nodes call :func:`dispatch_llm` to invoke the LLM via the
``celery-ingest`` worker pool instead of calling it directly.  The result is
awaited inside the FastAPI event loop via ``loop.run_in_executor`` so the
asyncio event loop is never blocked during the (potentially long) LLM call.

The worker streams tokens directly to ``fin:llm:tokens`` (Centrifugo native
consumer) and publishes one completion record to ``fin:llm:completions``
for the ``pg-persist`` beat worker.

Usage
-----
::

    from backend.graph.utils.celery_llm import dispatch_llm

    messages = prompt_template.format_messages(query=query)
    response_text = await dispatch_llm(
        messages,
        temperature=0.2,
        thread_id=thread_id,
        task_id=task_id,
        task_key="dm.llm_infer",
        node_name="decision_maker",
        json_mode=True,
    )
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


async def dispatch_llm(
    messages: list[BaseMessage],
    temperature: float = 0.3,
    thread_id: Optional[str] = None,
    task_id: Optional[int] = None,
    task_key: Optional[str] = None,
    node_name: Optional[str] = None,
    json_mode: bool = False,
    timeout: int = 300,
) -> str:
    """Dispatch an LLM invocation to a celery-ingest worker, await the result.

    Serialises the messages list with LangChain's canonical JSON encoder,
    dispatches the ``invoke_llm`` Celery task, then awaits the result in the
    FastAPI event loop via ``loop.run_in_executor`` (non-blocking).

    Args:
        messages:    Formatted LangChain messages ready for LLM invocation.
        temperature: Sampling temperature (default 0.3).
        thread_id:   LangGraph thread UUID for token routing and usage tracking.
        task_id:     Pre-created DB task row ID for token attribution.
        task_key:    Agent sub-task key for usage tracking.
        node_name:   Agent node name for usage tracking.
        json_mode:   Bind ``response_format={"type": "json_object"}`` when
                     the provider supports it (e.g. OpenAI-compatible endpoints).
        timeout:     Maximum seconds to wait for the Celery result (default 300).

    Returns:
        The full LLM response text.

    Raises:
        Exception: Re-raised from the celery task on LLM failure or timeout.
    """
    from langchain_core.load import dumps as lc_dumps  # noqa: PLC0415
    from backend.streaming.workers.llm_ingest import invoke_llm  # noqa: PLC0415

    messages_json = lc_dumps(messages)
    loop = asyncio.get_running_loop()
    async_result = invoke_llm.delay(
        messages_json=messages_json,
        temperature=temperature,
        thread_id=thread_id,
        task_id=task_id,
        task_key=task_key,
        node_name=node_name,
        json_mode=json_mode,
    )
    result: str = await loop.run_in_executor(
        None, lambda: async_result.get(timeout=timeout)
    )
    return result


__all__ = ["dispatch_llm"]
