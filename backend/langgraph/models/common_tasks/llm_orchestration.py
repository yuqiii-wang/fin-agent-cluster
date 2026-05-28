"""llm_orchestration — NodeTask: LLM-driven recovery decision for failed pipeline tasks.

When a task marked with ``is_required_llm_orchestration=True`` fails, the hosting
agent node runs this task to decide the next course of action.

Currently wired into the ``navigate_web`` pipeline to handle ``crawl_url`` failures.

Decision outcomes
-----------------
``action: "retry_propose"``
    Re-run ``propose_web_knowledge_urls`` with a new equity symbol proposed by the LLM,
    then retry ``crawl_url`` with the resulting URL.

``action: "fail"``
    The LLM cannot determine a useful alternative; propagate the original failure.

Execution layers
----------------
LangGraph layer (``_llm_orchestration_task`` decorated with ``@task``):
    Creates a Streaming task, delegates to the Celery stream worker, parses
    the structured JSON answer, and completes the task.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_orchestration_prompt``.
    Streams the LLM response; the structured JSON answer is extracted by the
    stream worker and returned in ``result["answer"]``.

Public exports
--------------
``llm_orchestration``       — ``NodeTask`` instance.
``LlmOrchestrationInput``   — Pydantic input model.
``LlmOrchestrationOutput``  — Pydantic output model.
``STREAM_PROMPT_BUILDERS``  — dict slice for the Celery stream prompt registry.
``HANDLERS``                — empty dict (streaming task; no completion handler).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import LLM_ORCH_DECIDE_ERROR
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "llm_orchestration"

_SYSTEM_PROMPT = """\
You are a financial research orchestration agent. A task in the pipeline has failed.
Your job is to determine the best recovery action.

Context: the pipeline fetches financial market data by proposing a URL for an equity symbol,
then crawling that URL. When crawling fails, you can propose a different equity symbol so
the URL-proposal step generates an alternative URL to try.

Available actions:
- "retry_propose": Propose a different equity ticker symbol. The pipeline will re-run
  propose_web_knowledge_urls with your suggested symbol to generate a new URL, then
  retry the crawl. Use this when the URL might be wrong, blocked, or the symbol format
  needs adjustment (e.g. "BRK-B" instead of "BRK.B", or a related ETF like "SPY").
- "fail": The failure cannot be recovered with a symbol change. Admit failure and halt
  this pipeline step.

Respond ONLY with a valid JSON object — no preamble, no explanation outside the JSON.

Schema:
{{
  "action":     "retry_propose" | "fail",
  "new_symbol": "<equity ticker to retry with — only when action=retry_propose, else empty string>",
  "reasoning":  "<1-3 sentence explanation of your decision>"
}}

Rules:
- Only use action="retry_propose" when you can identify a meaningful alternative symbol.
- new_symbol must be a valid equity ticker or index symbol, e.g. "AAPL", "^GSPC", "SPY".
- When action="fail", new_symbol must be empty string.
"""

_ORCHESTRATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", (
        "Failed task: {failed_task_name}\n"
        "Error message: {error_message}\n\n"
        "Original URL attempted: {original_url}\n\n"
        "Research objective: {objective}"
    )),
])


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class LlmOrchestrationInput(BaseModel):
    """Input for the llm_orchestration task.

    Attributes:
        failed_task_name: Name of the task that failed (e.g. ``"crawl_url"``).
        error_message:    Exception message or error description from the failed task.
        original_url:     URL that was attempted when the failure occurred.
        objective:        Research objective the pipeline was pursuing.
    """

    failed_task_name: str = Field(description="Name of the task that failed.")
    error_message: str = Field(description="Error or exception message from the failed task.")
    original_url: str = Field(description="URL that was attempted when the failure occurred.")
    objective: str = Field(description="Research objective driving this pipeline execution.")


class LlmOrchestrationOutput(BaseModel):
    """Output from the llm_orchestration task.

    Attributes:
        action:     Recovery decision:
                    ``"retry_propose"`` — re-run ``propose_web_knowledge_urls`` with
                    ``new_symbol`` and retry ``crawl_url``.
                    ``"fail"`` — propagate the original failure.
        new_symbol: Equity ticker to use for ``propose_web_knowledge_urls`` retry.
                    Non-empty only when ``action == "retry_propose"``.
        reasoning:  LLM's brief rationale for the decision.
    """

    action: Literal["retry_propose", "fail"] = Field(
        description="Recovery action: 'retry_propose' or 'fail'.",
    )
    new_symbol: str = Field(
        default="",
        description="Alternative equity symbol for retry (non-empty when action='retry_propose').",
    )
    reasoning: str = Field(default="", description="LLM reasoning for the decision.")


# ---------------------------------------------------------------------------
# Prompt builder (registered in STREAM_PROMPT_BUILDERS)
# ---------------------------------------------------------------------------


def _build_orchestration_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for llm_orchestration.

    Args:
        payload: Serialised :class:`LlmOrchestrationInput` dict.

    Returns:
        LangChain message list (SystemMessage + HumanMessage).
    """
    inp = LlmOrchestrationInput.model_validate(payload)
    return _ORCHESTRATION_PROMPT.format_messages(
        failed_task_name=inp.failed_task_name,
        error_message=inp.error_message[:2000],
        original_url=inp.original_url,
        objective=inp.objective,
    )


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_orchestration_prompt}


# ---------------------------------------------------------------------------
# Answer parser
# ---------------------------------------------------------------------------


def _parse_orchestration_answer(answer_dict: dict[str, Any]) -> LlmOrchestrationOutput:
    """Parse and validate the LLM JSON answer into a :class:`LlmOrchestrationOutput`.

    Invalid ``action`` values fall back to ``"fail"`` to avoid silently retrying
    with corrupted data.

    Args:
        answer_dict: Parsed JSON dict from the streaming answer.

    Returns:
        Validated :class:`LlmOrchestrationOutput`.
    """
    action = answer_dict.get("action", "fail")
    if action not in ("retry_propose", "fail"):
        logger.error(
            "[%s] unexpected action value %r from LLM; defaulting to 'fail'",
            LLM_ORCH_DECIDE_ERROR, action,
        )
        action = "fail"

    new_symbol = str(answer_dict.get("new_symbol", "")).strip()
    if action == "retry_propose" and not new_symbol:
        logger.error(
            "[%s] action='retry_propose' but new_symbol is empty; forcing action='fail'",
            LLM_ORCH_DECIDE_ERROR,
        )
        action = "fail"

    return LlmOrchestrationOutput(
        action=action,
        new_symbol=new_symbol if action == "retry_propose" else "",
        reasoning=str(answer_dict.get("reasoning", "")),
    )


# ---------------------------------------------------------------------------
# LangGraph layer — @task
# ---------------------------------------------------------------------------


@task
async def _llm_orchestration_task(
    task_input: TaskInput[LlmOrchestrationInput],
) -> TaskOutput[LlmOrchestrationOutput]:
    """LangGraph @task: stream LLM decision for pipeline task recovery.

    Creates a Streaming task, delegates to the Celery stream worker, parses
    the structured JSON decision, and completes the task.  On exception,
    marks the task as failed and re-raises so the caller can propagate the
    original pipeline failure.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`LlmOrchestrationInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`LlmOrchestrationOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Streaming",
    )
    try:
        result = await delegate_stream(
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            task_name=ctx.task_name,
            node_name=ctx.node_name,
            payload=payload,
        )
        output = _parse_orchestration_answer(result.get("answer", {}))
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=StreamingTaskOutput(
                thinking=result.get("thinking"),
                answer=output.model_dump(mode="json"),
            ).model_dump(),
            view_type="Streaming",
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Streaming",
        )
        raise


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

llm_orchestration: NodeTask[LlmOrchestrationInput, LlmOrchestrationOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Streaming LLM task: decides the recovery action when a pipeline task fails "
        "with is_required_llm_orchestration=True. Returns action='retry_propose' with "
        "a new equity symbol, or action='fail' to propagate the original failure."
    ),
    input_type=LlmOrchestrationInput,
    output_type=LlmOrchestrationOutput,
    task_fn=_llm_orchestration_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("llm_orchestration runs via the Celery stream worker.")
    ),
)

HANDLERS: dict = {_TASK_NAME: llm_orchestration.handler}

__all__ = [
    "llm_orchestration",
    "LlmOrchestrationInput",
    "LlmOrchestrationOutput",
    "STREAM_PROMPT_BUILDERS",
    "HANDLERS",
]
