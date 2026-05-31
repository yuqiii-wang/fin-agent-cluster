"""llm_orchestration_on_failure — NodeTask: LLM-driven recovery decision after a step failure.

When an AGENT node step raises, the generic step runner invokes this task to
study the failure and decide how to recover.  The decision is produced in two
LLM phases so the model never has to read every historical output at once:

Phase 1 — Task selection (lightweight, non-streaming)
    The node's *completed* task descriptors (task_id / task_name / description)
    plus the *failed* task output are presented to the LLM, which selects the
    subset of completed task_ids whose full outputs are worth reading to make a
    recovery decision.

Phase 2 — Recovery decision (streaming)
    The selected task outputs are loaded in full and streamed to the LLM, which
    proposes either:

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
    Runs phase 1 selection, loads selected histories, creates a Streaming task,
    delegates phase 2 to the Celery stream worker, parses the structured JSON
    decision, and completes the task.

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
from backend.celery_task.workers.tasks.stream_utils import extract_json_from_text
from backend.langgraph.agent.memory import (
    COMPLETED_STATUSES,
    FAILED_STATUSES,
    get_task_memory,
    get_task_outputs,
)
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import LLM_ORCH_DECIDE_ERROR
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.models.view_types import TASK_VIEW_STREAMING
from backend.llm.factory import get_llm

logger = logging.getLogger(__name__)

_TASK_NAME = "llm_orchestration_on_failure"

# Max number of completed task outputs the LLM may read in phase 2.
_MAX_SELECTED = 5


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
        selected_task_ids: Completed task_ids whose outputs informed the decision.
        reasoning:       Rationale carried to the regenerated streaming task so it
                         can avoid repeating the failure (1-4 sentences).
    """

    action: Literal["retry_from_step", "fail"] = Field(
        description="Recovery action to take."
    )
    retry_from_step: str | None = Field(
        default=None, description="Streaming step to regenerate when retrying."
    )
    selected_task_ids: list[str] = Field(
        default_factory=list, description="Task outputs used to decide."
    )
    reasoning: str = Field(default="", description="Rationale carried to the retried step.")


# ---------------------------------------------------------------------------
# Phase 1 — task selection prompt (non-streaming)
# ---------------------------------------------------------------------------

_SELECT_SYSTEM_TEMPLATE = """\
You are a recovery-planning agent for a financial data pipeline.

A pipeline step named "{failed_step}" just failed.  Below is the list of
COMPLETED tasks already produced by this node (each with an id, name and
description) and the FAILED task's output.

Decide which completed task outputs you need to READ IN FULL to understand the
failure and propose a fix.  Select only the most relevant tasks (at most {max_selected}).

Return ONLY a JSON object — no prose:
{{
  "selected_task_ids": ["<task_id>", ...]
}}
"""

_SELECT_HUMAN_TEMPLATE = """\
Objective: {objective}
Target: {target}
Failed step: {failed_step}
Failure reason: {failure_reason}

COMPLETED TASKS (id — name: description):
{descriptors}

FAILED TASK OUTPUT:
{failed_output}\
"""


def _format_descriptors(descriptors: list[dict[str, Any]]) -> str:
    """Render completed-task descriptors as a bullet list for the LLM."""
    if not descriptors:
        return "(none)"
    return "\n".join(
        f"- {d['task_id']} — {d['task_name']}: {d.get('description') or ''}"
        for d in descriptors
    )


# ---------------------------------------------------------------------------
# Phase 2 — decision prompt (streaming, registered in STREAM_PROMPT_BUILDERS)
# ---------------------------------------------------------------------------

_DECIDE_SYSTEM_TEMPLATE = """\
You are a recovery-planning agent for a financial data pipeline.

A pipeline step named "{failed_step}" failed.  Using the failure reason and the
full outputs of the selected prior tasks, decide how to recover.

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
  "selected_task_ids": [{selected_ids}],
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

SELECTED TASK OUTPUTS:
{histories}\
"""


def _build_orchestration_prompt(payload: dict) -> list:
    """Build LangChain messages for the phase-2 streaming decision.

    Args:
        payload: Serialised :class:`LlmOrchestrationInput` augmented with
                 ``histories`` (task_id -> output) and ``selected_task_ids``.

    Returns:
        ``[SystemMessage, HumanMessage]`` for the Celery stream worker.
    """
    inp = LlmOrchestrationInput.model_validate(payload)
    histories: dict[str, Any] = payload.get("histories", {})
    selected_ids: list[str] = payload.get("selected_task_ids", [])

    system_content = _DECIDE_SYSTEM_TEMPLATE.format(
        failed_step=inp.failed_step,
        retry_candidates=", ".join(inp.retry_candidates),
        selected_ids=", ".join(f'"{tid}"' for tid in selected_ids),
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
        histories=json.dumps(histories, indent=2, default=str),
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
            selected_task_ids=[str(t) for t in (answer_dict.get("selected_task_ids") or [])],
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
        selected_task_ids=[str(t) for t in (answer_dict.get("selected_task_ids") or [])],
        reasoning=str(answer_dict.get("reasoning", "")),
    )


# ---------------------------------------------------------------------------
# Phase 1 — task selection (non-streaming LLM call)
# ---------------------------------------------------------------------------


async def _select_task_ids(
    inp: LlmOrchestrationInput,
    descriptors: list[dict[str, Any]],
    failed_output: dict[str, Any],
) -> list[str]:
    """Ask the LLM which completed task outputs to read in full.

    Args:
        inp:           Orchestration input.
        descriptors:   Completed-task descriptor dicts (no outputs).
        failed_output: Output payload of the failed task (may be empty).

    Returns:
        Selected task_ids, capped at ``_MAX_SELECTED`` and restricted to known
        completed task_ids.  Empty when nothing is relevant.
    """
    valid_ids = {d["task_id"] for d in descriptors}
    if not valid_ids:
        return []

    system_content = _SELECT_SYSTEM_TEMPLATE.format(
        failed_step=inp.failed_step, max_selected=_MAX_SELECTED
    )
    human_content = _SELECT_HUMAN_TEMPLATE.format(
        objective=inp.objective or "(unspecified)",
        target=inp.target or "(unspecified)",
        failed_step=inp.failed_step,
        failure_reason=inp.failure_reason,
        descriptors=_format_descriptors(descriptors),
        failed_output=json.dumps(failed_output, indent=2, default=str),
    )

    llm = get_llm(streaming=False)
    response = await llm.ainvoke(
        [SystemMessage(content=system_content), HumanMessage(content=human_content)]
    )
    parsed = extract_json_from_text(str(getattr(response, "content", response)))
    selected = [str(t) for t in (parsed.get("selected_task_ids") or []) if str(t) in valid_ids]
    return selected[:_MAX_SELECTED]


# ---------------------------------------------------------------------------
# LangGraph layer — @task
# ---------------------------------------------------------------------------


@task
async def _llm_orchestration_on_failure_task(
    task_input: TaskInput[LlmOrchestrationInput],
) -> TaskOutput[LlmOrchestrationOutput]:
    """LangGraph @task: decide how to recover from a failed agent step.

    Phase 1 selects which completed task outputs to read; phase 2 streams the
    full selected outputs to the LLM and parses a structured recovery decision.

    Args:
        task_input: Typed envelope with node context and
                    :class:`LlmOrchestrationInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`LlmOrchestrationOutput`.
    """
    ctx = task_input.ctx
    inp = task_input.content

    # Phase 1 — gather descriptors + failed output, then select task_ids.
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
    failed = await get_task_memory(
        ctx.node_id, statuses=FAILED_STATUSES, with_output=True
    )
    failed_output: dict[str, Any] = next(
        (m.output for m in failed if m.task_name == inp.failed_step and m.output), {}
    )

    selected_ids = await _select_task_ids(inp, descriptors, failed_output)
    histories = await get_task_outputs(selected_ids) if selected_ids else {}

    payload = inp.model_dump(mode="json")
    payload["histories"] = histories
    payload["selected_task_ids"] = selected_ids

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
        "Streaming LLM task: study a failed agent step, dynamically select which prior "
        "task outputs to read, and decide whether to retry an earlier step with new inputs "
        "or fail."
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
