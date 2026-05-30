"""llm_orchestration_on_failure — NodeTask: generic LLM-driven step orchestrator for agent loops.

Used by AGENT-type nodes that define a named step loop (via ``AgentStepMixin``).
After each iteration, this task presents the iteration's execution summary to the
LLM and asks it to decide the next action.

Decision actions
----------------
``action: "finish"``
    The loop's finish condition is met. Stop the loop and proceed to final output.

``action: "next_iteration"``
    Start a fresh iteration from the first step.

``action: "retry_from_step"``
    Restart the next iteration from ``retry_from_step`` using ``input_overrides``
    to modify that step's behaviour.

``action: "fail"``
    No useful recovery is possible. The loop exits with best-available results.

Step info and overrides
-----------------------
The caller populates ``step_info`` with per-step descriptions and override schemas
so the LLM knows what overrides are valid for each step.

Execution layers
----------------
LangGraph layer (``_llm_orchestration_on_failure_task`` decorated with ``@task``):
    Creates a Streaming task, delegates to the Celery stream worker, parses
    the structured JSON answer, and completes the task.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_orchestration_prompt``.

Public exports
--------------
``llm_orchestration_on_failure``       — ``NodeTask`` instance.
``StepResult``              — Generic per-step execution record.
``StepInfo``                — Step descriptor (name, description, override schema).
``LlmOrchestrationInput``   — Pydantic input model.
``LlmOrchestrationOutput``  — Pydantic output model.
``STREAM_PROMPT_BUILDERS``  — dict slice for the Celery stream prompt registry.
``HANDLERS``                — empty dict (streaming task; no completion handler).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import LLM_ORCH_DECIDE_ERROR
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.models.view_types import TASK_VIEW_STREAMING

logger = logging.getLogger(__name__)

_TASK_NAME = "llm_orchestration_on_failure"

# ---------------------------------------------------------------------------
# Shared step models (used by both the task and agent step state)
# ---------------------------------------------------------------------------


class StepResult(BaseModel):
    """Execution record for a single step, surfaced to the LLM orchestration task.

    Attributes:
        step:           Step name from the step order list.
        success:        ``True`` when the step completed without raising.
        output_summary: Lightweight serialisable dict for LLM consumption.
                        Must not include heavy data blobs.
        failure_reason: Exception message when ``success=False``.
    """

    step: str
    success: bool
    output_summary: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None


class StepInfo(BaseModel):
    """Descriptor for a single step passed to the LLM for context.

    Attributes:
        name:                  Step name matching ``step_order``.
        description:           What this step does.
        input_override_schema: Mapping of override key → human-readable description.
    """

    name: str
    description: str
    input_override_schema: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class LlmOrchestrationInput(BaseModel):
    """Generic input for the llm_orchestration task.

    Attributes:
        iteration:        Current outer iteration counter (1-based).
        max_iterations:   Maximum loop iterations configured for this run.
        target:           Primary subject being processed (e.g. stock ticker, URL).
        objective:        Research objective driving this pipeline execution.
        step_order:       Canonical step execution order.
        step_info:        Per-step descriptors with override schemas for the LLM.
        step_results:     Per-step execution records for this iteration.
        failed_step:      Name of the step that failed; ``None`` if iteration completed.
        failure_reason:   Error message from the failed step; ``None`` if no failure.
        context_summary:  Node-specific key/value context (e.g. confirmed counts).
        finish_condition: Human-readable description of when the loop should finish.
    """

    iteration: int = Field(ge=1, description="Current outer iteration counter.")
    max_iterations: int = Field(ge=1, description="Maximum loop iterations.")
    target: str = Field(description="Primary subject being processed.")
    objective: str = Field(description="Research objective for this run.")
    step_order: list[str] = Field(description="Canonical step execution order.")
    step_info: list[StepInfo] = Field(
        default_factory=list,
        description="Per-step descriptors with override schemas.",
    )
    step_results: list[StepResult] = Field(
        default_factory=list,
        description="Per-step execution records for this iteration.",
    )
    failed_step: str | None = Field(default=None, description="Name of the failed step, if any.")
    failure_reason: str | None = Field(
        default=None, description="Error message from the failed step."
    )
    context_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Node-specific progress/state context for the LLM.",
    )
    finish_condition: str = Field(
        default="",
        description="Human-readable description of when to emit action='finish'.",
    )


class LlmOrchestrationOutput(BaseModel):
    """Output from the llm_orchestration task.

    Attributes:
        action:           Next loop action:
                          ``"finish"`` — loop complete; proceed to final output.
                          ``"next_iteration"`` — start a fresh iteration.
                          ``"retry_from_step"`` — restart from ``retry_from_step``
                          with ``input_overrides``.
                          ``"fail"`` — propagate failure; use best-available output.
        retry_from_step:  Step name to restart from (only when action="retry_from_step").
        input_overrides:  Step-specific input overrides for the retried step.
        reasoning:        LLM's brief rationale for the decision.
    """

    action: Literal["finish", "next_iteration", "retry_from_step", "fail"] = Field(
        description="Next loop action.",
    )
    retry_from_step: str | None = Field(
        default=None,
        description="Step to restart from when action='retry_from_step'.",
    )
    input_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Step-specific input overrides for the retried step.",
    )
    reasoning: str = Field(default="", description="LLM reasoning for the decision.")


# ---------------------------------------------------------------------------
# Prompt builder (registered in STREAM_PROMPT_BUILDERS)
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are a financial research orchestration agent managing an iterative pipeline.

The pipeline executes these steps in order to accomplish a research objective:
{step_descriptions}

Available actions:
- "finish":           The objective is sufficiently achieved. Stop the loop.
  Finish condition: {finish_condition}
- "next_iteration":   Start a fresh iteration from the beginning.
- "retry_from_step":  Restart the next iteration from a specific step with modified input.
- "fail":             Recovery is impossible. Halt the pipeline with best-available output.

Respond ONLY with a valid JSON object — no preamble, no explanation outside the JSON.

Schema:
{{
  "action":           "finish" | "next_iteration" | "retry_from_step" | "fail",
  "retry_from_step":  "<one of: {step_order}> or null",
  "input_overrides":  {{}},
  "reasoning":        "<1-3 sentence explanation>"
}}

Rules:
- Use "finish" only when the finish condition is met, or when max_iterations is reached
  and some useful result exists.
- Use "retry_from_step" only when you have a specific actionable override. Do not retry
  without overrides — use "next_iteration" instead.
- retry_from_step must be one of: {step_order}.
- When action is NOT "retry_from_step", set retry_from_step to null and input_overrides to {{}}.\
"""

_HUMAN_TEMPLATE = """\
Objective: {objective}
Target:    {target}
Iteration: {iteration} / {max_iterations}

Pipeline state:
{context_summary}

This iteration's step results:
{step_results_summary}

Failed step:    {failed_step}
Failure reason: {failure_reason}\
"""


def _build_orchestration_prompt(payload: dict) -> list:
    """Build LangChain messages for the llm_orchestration streaming task.

    Args:
        payload: Serialised :class:`LlmOrchestrationInput` dict.

    Returns:
        ``[SystemMessage, HumanMessage]`` for the Celery stream worker.
    """
    inp = LlmOrchestrationInput.model_validate(payload)

    step_desc_lines = []
    for si in inp.step_info:
        line = f"  {si.name}: {si.description}"
        if si.input_override_schema:
            overrides = ", ".join(
                f'"{k}" — {v}' for k, v in si.input_override_schema.items()
            )
            line += f"\n    overrides: {overrides}"
        step_desc_lines.append(line)
    step_descriptions = "\n".join(step_desc_lines) or "  (no step descriptions provided)"

    step_result_lines = []
    for sr in inp.step_results:
        status = "OK" if sr.success else "FAIL"
        line = f"  [{status}] {sr.step}: {json.dumps(sr.output_summary)}"
        if sr.failure_reason:
            line += f"\n        error: {sr.failure_reason[:300]}"
        step_result_lines.append(line)
    step_results_summary = "\n".join(step_result_lines) or "  (no steps ran this iteration)"

    context_lines = [f"  {k}: {v}" for k, v in inp.context_summary.items()]
    context_summary = "\n".join(context_lines) or "  (no context)"

    finish_condition = inp.finish_condition or "objective is accomplished"

    system_content = _SYSTEM_TEMPLATE.format(
        step_descriptions=step_descriptions,
        finish_condition=finish_condition,
        step_order=", ".join(inp.step_order),
    )
    human_content = _HUMAN_TEMPLATE.format(
        objective=inp.objective,
        target=inp.target,
        iteration=inp.iteration,
        max_iterations=inp.max_iterations,
        context_summary=context_summary,
        step_results_summary=step_results_summary,
        failed_step=inp.failed_step or "none",
        failure_reason=(inp.failure_reason or "none")[:500],
    )
    return [SystemMessage(content=system_content), HumanMessage(content=human_content)]


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_orchestration_prompt}


# ---------------------------------------------------------------------------
# Answer parser
# ---------------------------------------------------------------------------


def _parse_orchestration_answer(
    answer_dict: dict[str, Any],
    step_order: list[str],
) -> LlmOrchestrationOutput:
    """Parse and validate the LLM JSON answer into a :class:`LlmOrchestrationOutput`.

    Invalid ``action`` values fall back to ``"fail"`` to avoid silently proceeding
    with corrupted orchestration data.

    Args:
        answer_dict: Parsed JSON dict from the streaming answer.
        step_order:  Valid step names for ``retry_from_step`` validation.

    Returns:
        Validated :class:`LlmOrchestrationOutput`.
    """
    action = answer_dict.get("action", "fail")
    valid_actions = {"finish", "next_iteration", "retry_from_step", "fail"}
    if action not in valid_actions:
        logger.error(
            "[%s] unexpected action %r from LLM orchestration; defaulting to 'fail'",
            LLM_ORCH_DECIDE_ERROR, action,
        )
        action = "fail"

    retry_from_step: str | None = answer_dict.get("retry_from_step") or None
    if action == "retry_from_step":
        if not retry_from_step or retry_from_step not in step_order:
            logger.error(
                "[%s] action='retry_from_step' but retry_from_step=%r is invalid; "
                "falling back to 'next_iteration'",
                LLM_ORCH_DECIDE_ERROR, retry_from_step,
            )
            action = "next_iteration"
            retry_from_step = None

    input_overrides = answer_dict.get("input_overrides") or {}
    if not isinstance(input_overrides, dict):
        input_overrides = {}

    return LlmOrchestrationOutput(
        action=action,
        retry_from_step=retry_from_step if action == "retry_from_step" else None,
        input_overrides=input_overrides if action == "retry_from_step" else {},
        reasoning=str(answer_dict.get("reasoning", "")),
    )


# ---------------------------------------------------------------------------
# LangGraph layer — @task
# ---------------------------------------------------------------------------


@task
async def _llm_orchestration_on_failure_task(
    task_input: TaskInput[LlmOrchestrationInput],
) -> TaskOutput[LlmOrchestrationOutput]:
    """LangGraph @task: stream LLM step-routing decision for agent loops.

    Creates a Streaming task, delegates to the Celery stream worker, parses
    the structured JSON decision, and completes the task.  On exception,
    marks the task as failed and re-raises so the caller can handle the error.

    Args:
        task_input: Typed envelope with node context and
                    :class:`LlmOrchestrationInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`LlmOrchestrationOutput`.
    """
    ctx = task_input.ctx
    inp = task_input.content
    payload = inp.model_dump(mode="json")

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
        output = _parse_orchestration_answer(
            result.get("answer", {}),
            step_order=inp.step_order,
        )
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
        "Streaming LLM task: generic step orchestrator for AGENT-type node loops. "
        "Takes agent iteration state and step registry context; returns action "
        "('finish', 'next_iteration', 'retry_from_step', or 'fail') with optional "
        "retry_from_step and input_overrides."
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
    "StepResult",
    "StepInfo",
    "LlmOrchestrationInput",
    "LlmOrchestrationOutput",
    "STREAM_PROMPT_BUILDERS",
    "HANDLERS",
]
