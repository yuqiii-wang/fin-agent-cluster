"""llm_orchestration_on_failure — NodeTask: LLM-driven recovery decision after a step failure.

When an AGENT node step raises, the generic step runner invokes this task to
study the failure and decide how to recover.  Rather than reading every
historical task output, the task assembles a small, bounded diagnostic context:

* Completed-task descriptors — ``task_id`` / ``task_name`` / ``description`` only
  (no outputs), so the LLM knows what already ran.
* The *last failed* task output, truncated to the top 1k characters.
* This thread's recent WARNING+ logs (see
  :mod:`backend.langgraph.agent.error_log`), deduplicated and each truncated to
  the top 1k characters, so repeated messages and long stack traces never
  flood the prompt.

That context is streamed to the LLM (single phase), which proposes either:

    * ``"retry_from_step"`` — regenerate an earlier LLM *streaming* step (chosen
      from ``retry_candidates``).  No concrete values are injected; instead the
      failure reason and the decision's ``reasoning`` are forwarded to the
      regenerated streaming task so it can correct its output (e.g. rewrite an
      extraction script).  The new failure-context changes the task input hash so
      the retried task runs fresh (cache is bypassed naturally).
    * ``"fail"``            — the failure is unrecoverable.

Execution layers
----------------
LangGraph layer (``_llm_orchestration_on_failure_task`` decorated with ``@task``):
    Gathers the descriptors, last-failed output, and thread logs, creates a
    Streaming task, delegates the decision to the Celery stream worker, parses
    the structured JSON decision, and completes the task.

Celery layer (``STREAM_PROMPT_BUILDERS``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_orchestration_prompt``.

Public exports
--------------
``llm_orchestration_on_failure``   — ``NodeTask`` instance.
``LlmOrchestrationInput``          — Pydantic input model.
``LlmOrchestrationOutput``         — Pydantic output (decision) model.
``STREAM_PROMPT_BUILDERS``         — dict slice for the Celery stream prompt registry.
``HANDLERS``                       — handler slice (streaming task; raises if called directly).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.config import get_settings
from backend.langgraph.agent.error_log import get_thread_logs
from backend.langgraph.agent.memory import (
    COMPLETED_STATUSES,
    FAILED_STATUSES,
    get_task_memory,
)
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import LLM_ORCH_DECIDE_ERROR
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.models.view_types import TASK_VIEW_STREAMING

logger = logging.getLogger(__name__)

_TASK_NAME = "llm_orchestration_on_failure"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class LlmOrchestrationInput(BaseModel):
    """Input for the llm_orchestration_on_failure task.

    Attributes:
        failed_step:     Name of the step that raised.
        failure_reason:  Exception message captured from the failed step.
        objective:       One-sentence description of what the node is trying to
                         accomplish (used for LLM context).
        target:          Primary subject of the run (e.g. a symbol) for context.
        step_order:      Ordered list of all step names (for context only).
        retry_candidates: Subset of ``step_order`` that wrap an LLM *streaming*
                         task and can be re-run to regenerate their output.
                         ``retry_from_step`` must be chosen from this list.
        finish_condition: Human description of what a successful run looks like.
        context_summary: Small, serialisable extra context (no raw blobs).
    """

    failed_step: str = Field(description="Name of the step that raised.")
    failure_reason: str = Field(description="Exception message from the failed step.")
    objective: str = Field(default="", description="What the node is trying to do.")
    target: str = Field(default="", description="Primary subject of the run.")
    step_order: list[str] = Field(
        default_factory=list,
        description="Ordered step names (full pipeline, for context).",
    )
    retry_candidates: list[str] = Field(
        default_factory=list,
        description="Earlier LLM-streaming steps that may be regenerated; "
        "retry_from_step must be one of these.",
    )
    finish_condition: str = Field(
        default="", description="Description of a successful run."
    )
    context_summary: dict[str, Any] = Field(
        default_factory=dict, description="Small extra context for the LLM."
    )


class LlmOrchestrationOutput(BaseModel):
    """Recovery decision produced by the llm_orchestration_on_failure task.

    The decision never injects concrete corrected values (which would risk
    hallucinating numbers).  Instead it selects an earlier LLM *streaming* step
    to re-run; the step loop forwards the failure reason and this decision's
    reasoning to that step's streaming task so it regenerates its output with
    awareness of the prior failure.

    Attributes:
        action:          ``"retry_from_step"`` to regenerate an earlier streaming
                         step, or ``"fail"`` when recovery is impossible.
        retry_from_step: Streaming step to regenerate (required when action is
                         ``"retry_from_step"``; must be in ``retry_candidates``).
        reasoning:       Rationale carried to the regenerated streaming task so it
                         can avoid repeating the failure (1-4 sentences).
    """

    action: Literal["retry_from_step", "fail"] = Field(
        description="Recovery action to take."
    )
    retry_from_step: str | None = Field(
        default=None, description="Streaming step to regenerate when retrying."
    )
    reasoning: str = Field(default="", description="Rationale carried to the retried step.")


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, cap: int) -> str:
    """Return *text* truncated to *cap* characters with an elision marker."""
    if len(text) <= cap:
        return text
    return text[:cap] + " …[truncated]"


def _format_descriptors(descriptors: list[dict[str, Any]]) -> str:
    """Render completed-task descriptors as a bullet list for the LLM."""
    if not descriptors:
        return "(none)"
    return "\n".join(
        f"- {d['task_id']} — {d['task_name']}: {d.get('description') or ''}"
        for d in descriptors
    )


def _format_thread_logs(thread_logs: list[dict[str, Any]], char_cap: int) -> str:
    """Render captured thread WARNING+ logs as a bullet list for the LLM.

    Each message is truncated to *char_cap* characters; the occurrence count is
    shown so the LLM sees how often a duplicate fired without it being repeated.

    Args:
        thread_logs: Serialised :class:`ThreadLogEntry` dicts.
        char_cap:    Per-entry character cap.

    Returns:
        A bullet list, or ``"(none)"`` when empty.
    """
    if not thread_logs:
        return "(none)"
    lines: list[str] = []
    for entry in thread_logs:
        count = entry.get("count", 1)
        suffix = f" (x{count})" if count and count > 1 else ""
        message = _truncate(str(entry.get("message", "")), char_cap)
        lines.append(f"- [{entry.get('level')}] {entry.get('logger')}{suffix}: {message}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Decision prompt (streaming, registered in STREAM_PROMPT_BUILDERS)
# ---------------------------------------------------------------------------

_DECIDE_SYSTEM_TEMPLATE = """\
You are a recovery-planning agent for a financial data pipeline.

A pipeline step named "{failed_step}" failed.  Using the failure reason, the
truncated output of the failed task, and this thread's recent error/warning
logs, decide how to recover.

You may re-run ONE earlier LLM step from RETRY CANDIDATES.  Each candidate wraps
a streaming LLM task (e.g. it generates a data-extraction script).  Re-running it
regenerates its output from scratch, and your "reasoning" plus the failure reason
are handed to that task so it can fix the mistake (e.g. rewrite the script).

You CANNOT inject concrete values.  Do NOT invent or hallucinate any numbers,
fields, or data — the regenerated task must derive correct values itself from
the source content.  Your job is only to (a) pick which earlier streaming step to
regenerate and (b) explain, in "reasoning", what went wrong and what to fix.

If no candidate could plausibly fix the failure, fail.

Return ONLY a JSON object — no prose:
{{
  "action": "retry_from_step" | "fail",
  "retry_from_step": "<one of the RETRY CANDIDATES names, or null when action is fail>",
  "reasoning": "<1-4 sentences: what went wrong and what the regenerated task must fix>"
}}

Rules:
- "retry_from_step" MUST be one of the RETRY CANDIDATES: {retry_candidates}.
- Never propose concrete data values; "reasoning" is guidance only.
- Set "action" to "fail" only when no candidate could fix the failure.\
"""

_DECIDE_HUMAN_TEMPLATE = """\
Objective: {objective}
Target: {target}
Finish condition: {finish_condition}
Failed step: {failed_step}
Failure reason: {failure_reason}

STEP ORDER: {step_order}
RETRY CANDIDATES: {retry_candidates}

CONTEXT:
{context_summary}

COMPLETED TASKS (id — name: description):
{descriptors}

LAST FAILED TASK OUTPUT (truncated):
{failed_output}

THREAD ERROR/WARNING LOGS (deduplicated, truncated):
{thread_logs}\
"""


def _build_orchestration_prompt(payload: dict) -> list:
    """Build LangChain messages for the streaming recovery decision.

    Args:
        payload: Serialised :class:`LlmOrchestrationInput` augmented with
                 ``descriptors`` (completed-task id/name/description),
                 ``failed_output`` (truncated last-failed output string), and
                 ``thread_logs`` (serialised :class:`ThreadLogEntry` dicts).

    Returns:
        ``[SystemMessage, HumanMessage]`` for the Celery stream worker.
    """
    inp = LlmOrchestrationInput.model_validate(payload)
    descriptors: list[dict[str, Any]] = payload.get("descriptors", [])
    failed_output: str = payload.get("failed_output", "") or "(empty)"
    thread_logs: list[dict[str, Any]] = payload.get("thread_logs", [])
    char_cap = get_settings().AGENT_ERRLOG_CHAR_CAP

    system_content = _DECIDE_SYSTEM_TEMPLATE.format(
        failed_step=inp.failed_step,
        retry_candidates=", ".join(inp.retry_candidates),
    )
    human_content = _DECIDE_HUMAN_TEMPLATE.format(
        objective=inp.objective or "(unspecified)",
        target=inp.target or "(unspecified)",
        finish_condition=inp.finish_condition or "(unspecified)",
        failed_step=inp.failed_step,
        failure_reason=inp.failure_reason,
        step_order=", ".join(inp.step_order),
        retry_candidates=", ".join(inp.retry_candidates),
        context_summary=json.dumps(inp.context_summary, indent=2),
        descriptors=_format_descriptors(descriptors),
        failed_output=failed_output,
        thread_logs=_format_thread_logs(thread_logs, char_cap),
    )
    return [SystemMessage(content=system_content), HumanMessage(content=human_content)]


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_orchestration_prompt}


# ---------------------------------------------------------------------------
# Answer parser
# ---------------------------------------------------------------------------


def _parse_decision(answer_dict: dict[str, Any], retry_candidates: list[str]) -> LlmOrchestrationOutput:
    """Parse the LLM JSON answer into a :class:`LlmOrchestrationOutput`.

    Falls back to a ``"fail"`` decision when the structure is invalid or the
    proposed ``retry_from_step`` is not a valid retry candidate.

    Args:
        answer_dict:      Parsed JSON dict from the streaming answer.
        retry_candidates: Valid streaming step names for ``retry_from_step``.

    Returns:
        Validated :class:`LlmOrchestrationOutput`.
    """
    action = answer_dict.get("action")
    retry_from_step = answer_dict.get("retry_from_step")

    if action == "retry_from_step" and retry_from_step in retry_candidates:
        return LlmOrchestrationOutput(
            action="retry_from_step",
            retry_from_step=retry_from_step,
            reasoning=str(answer_dict.get("reasoning", "")),
        )

    if action != "fail":
        logger.error(
            "[%s] invalid decision action=%r retry_from_step=%r; defaulting to fail",
            LLM_ORCH_DECIDE_ERROR,
            action,
            retry_from_step,
        )
    return LlmOrchestrationOutput(
        action="fail",
        reasoning=str(answer_dict.get("reasoning", "")),
    )


# ---------------------------------------------------------------------------
# LangGraph layer — @task
# ---------------------------------------------------------------------------


@task
async def _llm_orchestration_on_failure_task(
    task_input: TaskInput[LlmOrchestrationInput],
) -> TaskOutput[LlmOrchestrationOutput]:
    """LangGraph @task: decide how to recover from a failed agent step.

    Assembles a bounded diagnostic context — completed-task descriptors, the
    truncated last-failed output, and the thread's deduplicated WARNING+ logs —
    then streams it to the LLM and parses a structured recovery decision.

    Args:
        task_input: Typed envelope with node context and
                    :class:`LlmOrchestrationInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`LlmOrchestrationOutput`.
    """
    ctx = task_input.ctx
    inp = task_input.content
    char_cap = get_settings().AGENT_ERRLOG_CHAR_CAP

    # Completed-task descriptors (task_id / task_name / description, no outputs).
    completed = await get_task_memory(
        ctx.node_id, statuses=COMPLETED_STATUSES, with_output=False
    )
    descriptors = [
        {
            "task_id": m.task_id,
            "task_name": m.task_name,
            "description": m.description,
        }
        for m in completed
    ]

    # Top 1k chars of the last failed task's output.
    failed = await get_task_memory(
        ctx.node_id, statuses=FAILED_STATUSES, with_output=True
    )
    failed_output_payload: dict[str, Any] = next(
        (m.output for m in reversed(failed) if m.task_name == inp.failed_step and m.output),
        {},
    )
    failed_output = _truncate(
        json.dumps(failed_output_payload, indent=2, default=str), char_cap
    )

    # This thread's deduplicated WARNING+ logs (each already ≤ char_cap).
    thread_logs = [
        e.model_dump(mode="json") for e in await get_thread_logs(ctx.thread_id)
    ]

    payload = inp.model_dump(mode="json")
    payload["descriptors"] = descriptors
    payload["failed_output"] = failed_output
    payload["thread_logs"] = thread_logs

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type=TASK_VIEW_STREAMING,
    )
    try:
        result = await delegate_stream(
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            task_name=ctx.task_name,
            node_name=ctx.node_name,
            payload=payload,
        )
        output = _parse_decision(result.get("answer", {}), inp.retry_candidates)
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=StreamingTaskOutput(
                thinking=result.get("thinking"),
                answer=output.model_dump(mode="json"),
            ).model_dump(),
            view_type=TASK_VIEW_STREAMING,
        )
        return TaskOutput(ctx=ctx, content=output, thinking=result.get("thinking"))
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type=TASK_VIEW_STREAMING,
        )
        raise


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

llm_orchestration_on_failure: NodeTask[LlmOrchestrationInput, LlmOrchestrationOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Streaming LLM task: study a failed agent step using completed-task descriptors, "
        "the truncated last-failed output, and the thread's deduplicated error/warning logs, "
        "then decide whether to retry an earlier streaming step or fail."
    ),
    input_type=LlmOrchestrationInput,
    output_type=LlmOrchestrationOutput,
    task_fn=_llm_orchestration_on_failure_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("llm_orchestration_on_failure runs via the Celery stream worker.")
    ),
)

HANDLERS: dict = {_TASK_NAME: llm_orchestration_on_failure.handler}

__all__ = [
    "llm_orchestration_on_failure",
    "LlmOrchestrationInput",
    "LlmOrchestrationOutput",
    "STREAM_PROMPT_BUILDERS",
    "HANDLERS",
]
