"""peer_orchestration — NodeTask: LLM-driven step orchestration for the peer corr-validation loop.

After each iteration of the peer-validation loop (successful or partially failed),
this task presents the iteration's execution summary to the LLM and asks it to
decide the next action.

Decision actions
----------------
``action: "finish"``
    Enough peers have been confirmed. Stop the loop and proceed to final selection.

``action: "next_iteration"``
    Start a fresh iteration from ``propose_url`` with no input overrides.

``action: "retry_from_step"``
    Restart the next iteration from ``retry_from_step`` using ``input_overrides``
    to modify that step's behaviour (e.g. inject a custom URL or peer list).

``action: "fail"``
    No useful recovery is possible. The loop exits; best-available fallback applies.

Input overrides per step
------------------------
- ``propose_url``:    ``{"custom_url": "<url>"}`` or ``{"stock_name_hint": "<hint>"}``
- ``navigate_web``:   ``{"peers": ["SYM1", "SYM2"]}``  — inject tickers directly
- ``fetch_stats``:    ``{"symbols": ["SYM1", ...]}``    — retry specific symbols
- ``calculate_corr``: ``{"peers": ["SYM1", ...]}``      — retry corr for subset

Execution layers
----------------
LangGraph layer (``_peer_orchestration_task`` decorated with ``@task``):
    Creates a Streaming task, delegates to the Celery stream worker, parses the
    JSON decision, and completes the task.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_peer_orchestration_prompt``.

Public exports
--------------
``peer_orchestration``      — ``NodeTask`` instance used by ``AnalyzePeersNode``.
``PeerOrchestrationInput``  — Pydantic input model.
``PeerOrchestrationOutput`` — Pydantic output model.
``TopCorrPeer``             — Helper model for top-corr summary.
``STREAM_PROMPT_BUILDERS``  — dict slice for registration in ``stream_task.py``.
``HANDLERS``                — dict with raising lambda (streaming task; no completion handler).
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
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.models.view_types import TASK_VIEW_STREAMING
from backend.langgraph.nodes.prepare_peers.agent_steps import STEP_ORDER, StepResult

logger = logging.getLogger(__name__)

_TASK_NAME = "peer_orchestration"

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are a financial research orchestration agent managing a peer-correlation validation loop.

The loop identifies peer companies for a target equity by executing these steps in order:
  1. propose_url      — propose a URL for peer discovery
  2. navigate_web     — crawl the URL and extract peer tickers
  3. fetch_stats      — fetch OHLCV stats for target and peers
  4. filter_co_index  — remove peers not in the same index as the target
  5. calculate_corr   — compute Pearson correlation (target vs each peer, 252-day window)
  6. analyze_corr     — classify peers as confirmed (abs(r) >= 0.75) or rejected

Your job: decide the next action given the current loop state.

Available actions:
- "finish":           Enough confirmed peers ({min_confirmed_to_exit}+). Stop the loop.
- "next_iteration":   Start a fresh iteration — propose a new URL.
- "retry_from_step":  Restart next iteration from a specific step with modified input.
- "fail":             Recovery is impossible; no useful peers can be found.

Retry step input overrides (provide ONLY for "retry_from_step"):
- propose_url:    {{"custom_url": "<url>"}} OR {{"stock_name_hint": "<ticker or name hint>"}}
- navigate_web:   {{"peers": ["SYM1", "SYM2"]}}  — inject tickers directly, skip crawl
- fetch_stats:    {{"symbols": ["SYM1", ...]}}    — retry only these symbols
- calculate_corr: {{"peers": ["SYM1", ...]}}      — recompute corr for this peer subset

Respond ONLY with a valid JSON object — no preamble, no explanation outside the JSON.

Schema:
{{
  "action":           "finish" | "next_iteration" | "retry_from_step" | "fail",
  "retry_from_step":  "<one of: {step_order}> or null",
  "input_overrides":  {{}},
  "reasoning":        "<1-3 sentence explanation>"
}}

Rules:
- Use "finish" if confirmed_count >= {min_confirmed_to_exit}, OR iteration == max_iterations
  and confirmed_count > 0.
- Use "retry_from_step" only when you have a specific actionable override (e.g. a better URL,
  known tickers to inject directly, or a symbol subset that warrants a retry).
  Do not retry without overrides — use "next_iteration" instead.
- retry_from_step must be one of: {step_order}.
- When action is NOT "retry_from_step", set retry_from_step to null and input_overrides to {{}}.\
"""

_HUMAN_TEMPLATE = """\
Target stock:          {target}
Iteration:             {iteration} / {max_iterations}
Confirmed peers:       {confirmed_count}
Excluded URLs tried:   {excluded_url_count}
Excluded peers total:  {excluded_peer_count}

Top correlation scores seen:
{top_corr_summary}

This iteration's step results:
{step_results_summary}

Failed step:    {failed_step}
Failure reason: {failure_reason}\
"""


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class TopCorrPeer(BaseModel):
    """One entry in the top-corr summary passed to the LLM.

    Attributes:
        symbol: Peer stock ticker.
        corr:   Best abs-corr score seen (0.0–1.0).
    """

    symbol: str
    corr: float


class PeerOrchestrationInput(BaseModel):
    """Input for the peer_orchestration task.

    Attributes:
        iteration:              Current outer iteration counter (1-based).
        target:                 Target stock ticker.
        confirmed_count:        Unique confirmed peers across all iterations so far.
        excluded_url_count:     Number of URLs already tried.
        excluded_peer_count:    Number of peers already processed (confirmed + rejected).
        step_results:           Per-step execution records for this iteration.
        failed_step:            Name of the step that failed; ``None`` if iteration completed.
        failure_reason:         Error message from the failed step; ``None`` if no failure.
        top_corr_peers:         Top-N peers by abs-corr for LLM context.
        min_confirmed_to_exit:  Confirmed-peer threshold to trigger an early "finish".
        max_iterations:         Maximum loop iterations configured for this run.
    """

    iteration: int = Field(ge=1, description="Current outer iteration counter.")
    target: str = Field(description="Target stock ticker.")
    confirmed_count: int = Field(ge=0, description="Unique confirmed peers so far.")
    excluded_url_count: int = Field(ge=0, description="URLs already tried.")
    excluded_peer_count: int = Field(ge=0, description="Peers already processed.")
    step_results: list[StepResult] = Field(
        default_factory=list,
        description="Per-step execution records for this iteration.",
    )
    failed_step: str | None = Field(default=None, description="Name of the failed step, if any.")
    failure_reason: str | None = Field(
        default=None, description="Error message from the failed step."
    )
    top_corr_peers: list[TopCorrPeer] = Field(
        default_factory=list,
        description="Top-N peers by abs-corr for LLM context.",
    )
    min_confirmed_to_exit: int = Field(
        default=2, description="Min confirmed peers for early finish."
    )
    max_iterations: int = Field(default=3, description="Max loop iterations.")


class PeerOrchestrationOutput(BaseModel):
    """Output from the peer_orchestration task.

    Attributes:
        action:           Next loop action.
        retry_from_step:  Step name to restart from (only when action="retry_from_step").
        input_overrides:  Step-specific input overrides for the retried step.
        reasoning:        LLM's rationale for the decision.
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


def _build_peer_orchestration_prompt(payload: dict) -> list:
    """Build LangChain messages for the peer_orchestration streaming task.

    Args:
        payload: Serialised :class:`PeerOrchestrationInput` dict.

    Returns:
        ``[SystemMessage, HumanMessage]`` for the Celery stream worker.
    """
    inp = PeerOrchestrationInput.model_validate(payload)

    step_result_lines = []
    for sr in inp.step_results:
        status = "OK" if sr.success else "FAIL"
        line = f"  [{status}] {sr.step}: {json.dumps(sr.output_summary)}"
        if sr.failure_reason:
            line += f"\n        error: {sr.failure_reason[:300]}"
        step_result_lines.append(line)
    step_results_summary = "\n".join(step_result_lines) or "  (no steps ran this iteration)"

    top_corr_lines = [f"  {p.symbol}: {p.corr:.4f}" for p in inp.top_corr_peers]
    top_corr_summary = "\n".join(top_corr_lines) or "  (none yet)"

    system_content = _SYSTEM_TEMPLATE.format(
        min_confirmed_to_exit=inp.min_confirmed_to_exit,
        max_iterations=inp.max_iterations,
        step_order=", ".join(STEP_ORDER),
    )
    human_content = _HUMAN_TEMPLATE.format(
        target=inp.target,
        iteration=inp.iteration,
        max_iterations=inp.max_iterations,
        confirmed_count=inp.confirmed_count,
        excluded_url_count=inp.excluded_url_count,
        excluded_peer_count=inp.excluded_peer_count,
        top_corr_summary=top_corr_summary,
        step_results_summary=step_results_summary,
        failed_step=inp.failed_step or "none",
        failure_reason=(inp.failure_reason or "none")[:500],
    )
    return [SystemMessage(content=system_content), HumanMessage(content=human_content)]


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_peer_orchestration_prompt}


# ---------------------------------------------------------------------------
# Answer parser
# ---------------------------------------------------------------------------


def _parse_orchestration_answer(answer_dict: dict[str, Any]) -> PeerOrchestrationOutput:
    """Parse and validate the LLM JSON answer into a :class:`PeerOrchestrationOutput`.

    Invalid ``action`` values fall back to ``"fail"`` to avoid silently
    proceeding with corrupted orchestration data.

    Args:
        answer_dict: Parsed JSON dict from the streaming answer.

    Returns:
        Validated :class:`PeerOrchestrationOutput`.
    """
    action = answer_dict.get("action", "fail")
    valid_actions = {"finish", "next_iteration", "retry_from_step", "fail"}
    if action not in valid_actions:
        logger.error(
            "[AP-007] unexpected action %r from LLM peer orchestration; defaulting to 'fail'",
            action,
        )
        action = "fail"

    retry_from_step: str | None = answer_dict.get("retry_from_step") or None
    if action == "retry_from_step":
        if not retry_from_step or retry_from_step not in STEP_ORDER:
            logger.error(
                "[AP-007] action='retry_from_step' but retry_from_step=%r is invalid; "
                "falling back to 'next_iteration'",
                retry_from_step,
            )
            action = "next_iteration"
            retry_from_step = None

    input_overrides = answer_dict.get("input_overrides") or {}
    if not isinstance(input_overrides, dict):
        input_overrides = {}

    return PeerOrchestrationOutput(
        action=action,
        retry_from_step=retry_from_step,
        input_overrides=input_overrides,
        reasoning=str(answer_dict.get("reasoning", "")),
    )


# ---------------------------------------------------------------------------
# LangGraph @task
# ---------------------------------------------------------------------------


@task
async def _peer_orchestration_task(
    task_input: TaskInput[PeerOrchestrationInput],
) -> TaskOutput[PeerOrchestrationOutput]:
    """LangGraph task: stream peer orchestration decision from LLM.

    Args:
        task_input: Typed task input with peer orchestration context.

    Returns:
        ``TaskOutput`` wrapping a :class:`PeerOrchestrationOutput`.

    Raises:
        Exception: When the stream delegation or answer parsing fails.
    """
    ctx = task_input.ctx
    inp = task_input.content
    payload = inp.model_dump()

    await create_task(
        ctx.thread_id,
        ctx.node_id,
        ctx.node_name,
        ctx.task_id,
        ctx.task_name,
        payload,
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
        answer_dict = result.get("answer", {})
        output = _parse_orchestration_answer(answer_dict)
        await complete_task(
            ctx.thread_id,
            ctx.node_id,
            ctx.node_name,
            ctx.task_id,
            ctx.task_name,
            output_data=StreamingTaskOutput(
                thinking=result.get("thinking"),
                answer=output.model_dump(),
            ).model_dump(),
            view_type=TASK_VIEW_STREAMING,
        )
        return TaskOutput(ctx=ctx, content=output, thinking=result.get("thinking"))
    except Exception as exc:
        logger.error(
            "[AP-007] peer_orchestration task failed iter=%d target=%r: %s",
            inp.iteration,
            inp.target,
            exc,
        )
        await complete_task(
            ctx.thread_id,
            ctx.node_id,
            ctx.node_name,
            ctx.task_id,
            ctx.task_name,
            failed=True,
            error=str(exc),
            view_type=TASK_VIEW_STREAMING,
        )
        raise


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

peer_orchestration: NodeTask[PeerOrchestrationInput, PeerOrchestrationOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Streaming LLM task: decides the next action after each peer corr-validation "
        "iteration. Returns finish, next_iteration, retry_from_step (with step name and "
        "input overrides), or fail."
    ),
    input_type=PeerOrchestrationInput,
    output_type=PeerOrchestrationOutput,
    task_fn=_peer_orchestration_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("peer_orchestration runs via the Celery stream worker.")
    ),
    is_required_llm_orchestration=True,
    cache_ttl_seconds=0,
)

HANDLERS: dict = {_TASK_NAME: peer_orchestration.handler}

__all__ = [
    "peer_orchestration",
    "PeerOrchestrationInput",
    "PeerOrchestrationOutput",
    "TopCorrPeer",
    "STREAM_PROMPT_BUILDERS",
    "HANDLERS",
]
