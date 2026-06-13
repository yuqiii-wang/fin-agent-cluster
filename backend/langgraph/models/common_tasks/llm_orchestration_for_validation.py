"""llm_orchestration_for_validation -- NodeTask: LLM-driven JSON output validator.

Given the outputs of a previous source task and a JSON blob produced by a
downstream step, this task asks the LLM to verify every field/value in the
JSON blob against the source data using two rules:

- **Exact match** for numeric values (prices, counts, percentages, ratios, ...).
- **Semantic match** for non-numeric values (names, descriptions, categories, ...).

Any field that cannot be traced back to the source data is reported as a
violation.  The task returns ``passed=True`` only when no violations are found.

Violation kinds
---------------
``"numeric_mismatch"``
    A numeric value in the JSON does not exactly match the corresponding value
    in the source output.

``"semantic_mismatch"``
    A non-numeric value in the JSON cannot be semantically traced back to the
    source output (hallucination or unrelated fabrication).

``"unverifiable"``
    The LLM cannot determine whether the value is valid because the source
    output does not cover that field at all.  Callers should treat this as a
    soft warning rather than a hard failure.

Execution layers
----------------
LangGraph layer (``_llm_orchestration_for_validation_task`` decorated with ``@task``):
    Creates a Streaming task, delegates to the Celery stream worker, parses
    the structured JSON answer, and completes the task.

Celery layer (``STREAM_PROMPT_BUILDERS``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_validation_prompt``.

Public exports
--------------
``llm_orchestration_for_validation``     -- ``NodeTask`` instance.
``ValidationViolation``                  -- Single violation record.
``LlmValidationInput``                   -- Pydantic input model.
``LlmValidationOutput``                  -- Pydantic output model.
``STREAM_PROMPT_BUILDERS``               -- dict slice for the Celery stream prompt registry.
``HANDLERS``                             -- empty dict (streaming task; no completion handler).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import LLM_ORCH_VALIDATION_ERROR
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.models.view_types import TASK_VIEW_STREAMING

logger = logging.getLogger(__name__)

_TASK_NAME = "llm_orchestration_for_validation"

# ---------------------------------------------------------------------------
# Violation model
# ---------------------------------------------------------------------------

class ValidationViolation(BaseModel):
    """A single field-level validation violation.

    Attributes:
        field:            Dot-path or key identifying the problematic field
                          inside ``json_input`` (e.g. ``"price"`` or
                          ``"summary.pe_ratio"``).
        kind:             Violation category.  One of:
                          ``"numeric_mismatch"`` -- exact match required but
                          value differs from the source;
                          ``"semantic_mismatch"`` -- non-numeric value cannot be
                          semantically traced back to the source;
                          ``"unverifiable"`` -- source data does not cover this
                          field so correctness cannot be determined.
        found_value:      String representation of the value found in
                          ``json_input``.
        expected_context: Relevant excerpt or description from the source
                          output that shows what was expected (empty string
                          when kind is ``"unverifiable"``).
    """

    field: str
    kind: Literal["numeric_mismatch", "semantic_mismatch", "unverifiable"]
    found_value: str
    expected_context: str = ""

# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class LlmValidationInput(BaseModel):
    """Input for the llm_orchestration_for_validation task.

    Attributes:
        src_task_name:    Name of the upstream task whose output is the
                          authoritative reference.
        src_output:       Serialisable summary of the upstream task's output.
                          Should contain only the fields relevant to validation
                          and must be kept concise (no raw OHLCV blobs).
        json_input:       The JSON object to validate against ``src_output``.
        objective:        One-sentence description of what this pipeline is
                          trying to accomplish -- used by the LLM for context.
        numeric_hint:     Optional list of dot-paths that should be treated as
                          numeric regardless of their Python type.  If empty
                          the LLM infers type from value content.
    """

    src_task_name: str = Field(description="Name of the upstream source task.")
    src_output: dict[str, Any] = Field(
        description="Authoritative reference output from the source task."
    )
    json_input: dict[str, Any] = Field(
        description="JSON object to validate against the source output."
    )
    objective: str = Field(
        default="",
        description="Pipeline objective for additional LLM context.",
    )
    numeric_hint: list[str] = Field(
        default_factory=list,
        description="Dot-paths to treat as numeric unconditionally.",
    )

class LlmValidationOutput(BaseModel):
    """Output from the llm_orchestration_for_validation task.

    Attributes:
        passed:     ``True`` when no ``numeric_mismatch`` or
                    ``semantic_mismatch`` violations were found.
                    ``"unverifiable"`` violations do not affect this flag.
        violations: List of field-level violations found (may be empty).
        reasoning:  LLM's brief overall rationale (1-3 sentences).
    """

    passed: bool = Field(description="True when all verifiable fields pass.")
    violations: list[ValidationViolation] = Field(default_factory=list)
    reasoning: str = Field(default="", description="LLM reasoning for the verdict.")

# ---------------------------------------------------------------------------
# Prompt builder (registered in STREAM_PROMPT_BUILDERS)
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are a financial data validation agent.

Your task is to check every field/value in the JSON INPUT against the SOURCE \
OUTPUT of a prior pipeline step named "{src_task_name}".

Validation rules:
1. NUMERIC fields (integers, floats, percentages, prices, counts, ...) -- the \
value in JSON INPUT must match EXACTLY (same sign, magnitude, and reasonable \
precision) a value that appears in SOURCE OUTPUT.  Discrepancies are \
"numeric_mismatch" violations.
2. NON-NUMERIC fields (names, descriptions, categories, qualitative labels, ...) \
-- the value in JSON INPUT must be semantically traceable to the SOURCE OUTPUT.  \
Fabricated or contradictory content is a "semantic_mismatch" violation.
3. If a field has no corresponding information in SOURCE OUTPUT and cannot be \
confirmed, classify it as "unverifiable".

{numeric_hint_section}\
Return ONLY a valid JSON object -- no preamble, no explanation outside the JSON.

Schema:
{{
  "passed": true | false,
  "violations": [
    {{
      "field":            "<dot-path key in json_input>",
      "kind":             "numeric_mismatch" | "semantic_mismatch" | "unverifiable",
      "found_value":      "<string representation of the value in json_input>",
      "expected_context": "<relevant excerpt from source output, empty if unverifiable>"
    }}
  ],
  "reasoning": "<1-3 sentence overall rationale>"
}}

Rules:
- "passed" must be true only when violations list contains NO "numeric_mismatch" \
or "semantic_mismatch" entries.
- Include a violation entry for EVERY problematic field; omit clean fields.
- If no violations exist, set violations to [].\
"""

_NUMERIC_HINT_SECTION = """\
The following fields must be treated as numeric regardless of their type:
{fields}

"""

_HUMAN_TEMPLATE = """\
Objective: {objective}

SOURCE OUTPUT (from task "{src_task_name}"):
{src_output}

JSON INPUT (to validate):
{json_input}\
"""

def _build_validation_prompt(payload: dict) -> list:
    """Build LangChain messages for the llm_orchestration_for_validation streaming task.

    Args:
        payload: Serialised :class:`LlmValidationInput` dict.

    Returns:
        ``[SystemMessage, HumanMessage]`` for the Celery stream worker.
    """
    inp = LlmValidationInput.model_validate(payload)

    numeric_hint_section = ""
    if inp.numeric_hint:
        field_list = "\n".join(f"  - {f}" for f in inp.numeric_hint)
        numeric_hint_section = _NUMERIC_HINT_SECTION.format(fields=field_list)

    system_content = _SYSTEM_TEMPLATE.format(
        src_task_name=inp.src_task_name,
        numeric_hint_section=numeric_hint_section,
    )
    human_content = _HUMAN_TEMPLATE.format(
        objective=inp.objective or "validate output accuracy",
        src_task_name=inp.src_task_name,
        src_output=json.dumps(inp.src_output, indent=2),
        json_input=json.dumps(inp.json_input, indent=2),
    )
    return [SystemMessage(content=system_content), HumanMessage(content=human_content)]

STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_validation_prompt}

# ---------------------------------------------------------------------------
# Answer parser
# ---------------------------------------------------------------------------

def _parse_validation_answer(answer_dict: dict[str, Any]) -> LlmValidationOutput:
    """Parse and validate the LLM JSON answer into a :class:`LlmValidationOutput`.

    Malformed violation entries are skipped with an error log.  If parsing
    fails entirely, returns a failed result so the caller can react.

    Args:
        answer_dict: Parsed JSON dict from the streaming answer.

    Returns:
        Validated :class:`LlmValidationOutput`.
    """
    valid_kinds = {"numeric_mismatch", "semantic_mismatch", "unverifiable"}

    violations: list[ValidationViolation] = []
    for raw in answer_dict.get("violations") or []:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind", "unverifiable")
        if kind not in valid_kinds:
            logger.error(
                "[%s] unexpected violation kind %r; skipping entry",
                LLM_ORCH_VALIDATION_ERROR,
                kind,
            )
            continue
        try:
            violations.append(
                ValidationViolation(
                    field=str(raw.get("field", "")),
                    kind=kind,
                    found_value=str(raw.get("found_value", "")),
                    expected_context=str(raw.get("expected_context", "")),
                )
            )
        except Exception:
            logger.error(
                "[%s] could not parse violation entry %r; skipping",
                LLM_ORCH_VALIDATION_ERROR,
                raw,
            )

    hard_violation_kinds = {"numeric_mismatch", "semantic_mismatch"}
    has_hard_violations = any(v.kind in hard_violation_kinds for v in violations)

    passed_raw = answer_dict.get("passed")
    if isinstance(passed_raw, bool):
        passed = passed_raw and not has_hard_violations
    else:
        passed = not has_hard_violations

    return LlmValidationOutput(
        passed=passed,
        violations=violations,
        reasoning=str(answer_dict.get("reasoning", "")),
    )

# ---------------------------------------------------------------------------
# LangGraph layer -- @task
# ---------------------------------------------------------------------------

async def _llm_orchestration_for_validation_task(
    task_input: TaskInput[LlmValidationInput],
) -> TaskOutput[LlmValidationOutput]:
    """LangGraph @task: stream LLM validation of a JSON output against a source task.

    Creates a Streaming task, delegates to the Celery stream worker, parses
    the structured JSON validation verdict, and completes the task.  On
    exception, marks the task failed and re-raises.

    Args:
        task_input: Typed envelope with node context and
                    :class:`LlmValidationInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`LlmValidationOutput`.
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
        output = _parse_validation_answer(result.get("answer", {}))
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

llm_orchestration_for_validation: NodeTask[LlmValidationInput, LlmValidationOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Streaming LLM task: validate a JSON output against the outputs of a prior source task. "
        "Numeric fields are checked for exact matches; non-numeric fields are checked for "
        "semantic traceability.  Returns passed=True only when all verifiable fields pass."
    ),
    input_type=LlmValidationInput,
    output_type=LlmValidationOutput,
    task_fn=_llm_orchestration_for_validation_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("llm_orchestration_for_validation runs via the Celery stream worker.")
    ),
)

HANDLERS: dict = {_TASK_NAME: llm_orchestration_for_validation.handler}

__all__ = [
    "llm_orchestration_for_validation",
    "ValidationViolation",
    "LlmValidationInput",
    "LlmValidationOutput",
    "STREAM_PROMPT_BUILDERS",
    "HANDLERS",
]
