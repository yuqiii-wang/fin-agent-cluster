"""study_web_content -- NodeTask: LLM-stream generation of a Python transform script.

Streams the Markdown content from a crawled financial page to the LLM and asks
it to write a self-contained Python script that reads the Markdown from stdin
and outputs structured financial data as a JSON object to stdout.

Outputs
-------
``source_markdown``
    The raw Markdown text passed to the LLM (forwarded from ``html_to_markdown``);
    used as stdin when ``run_sandbox`` executes the generated script.

``transform_script``
    A stdlib-only Python script that reads the Markdown from stdin and prints a
    single JSON object containing the extracted financial data to stdout.

``reasoning``
    LLM's brief rationale for what data was found and how the script extracts it.

``has_popup``
    ``True`` when the LLM determined the page cannot yield financial data -- blocked by a
    pop-up/consent/GDPR overlay, contains only privacy/cookie/ads content, is empty or very
    short, or is any other access barrier.  When ``True`` the pipeline triggers the barrier-clear
    flow (``propose_playwright_script`` -> sandbox execution) and retries.

Failure behaviour
-----------------
Stream failure propagates so that ``seq.py`` can mark the overall task failed.

Execution layers
----------------
LangGraph layer (``_study_web_content_task`` decorated with ``@task``):
    The pg cache check is handled upstream by ``run_task`` via ``pg_cache_fn``.
    This function is only reached on a cache miss.  Creates a Streaming task,
    delegates to the Celery stream worker, parses the JSON answer from the LLM,
    injects ``source_markdown`` from the input, and completes the task.

Celery layer (``stream_task.run_stream``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_study_prompt``.
    Streams the LLM response; the structured JSON answer is extracted by the
    stream worker and returned in ``result["answer"]``.

Public exports
--------------
``study_web_content``       -- ``NodeTask`` instance.
``StudyWebContentInput``    -- Pydantic input model.
``StudyWebContentOutput``   -- Pydantic output model.
``STREAM_PROMPT_BUILDERS``  -- dict slice for ``stream_task._get_stream_prompt_builders``.
``HANDLERS``                -- empty dict (streaming task; no completion handler).
"""

from __future__ import annotations

import hashlib
import json
import logging

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_stream
from backend.config import get_settings
from backend.db.postgres.connection import raw_conn
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "study_web_content"
_CACHE_TTL_HOURS = 4

_SYSTEM_PROMPT = """\
You are a financial data extraction engineer. You will be given the Markdown content of a \
financial web page and a research objective. Your job is to write a self-contained Python script \
that:

1. Reads the full Markdown text from sys.stdin.
2. Parses and extracts the relevant structured financial data that addresses the objective.
3. Writes exactly one JSON object to stdout via print(json.dumps(...)).

Additionally, inspect the page content BEFORE writing the script:
- Set "has_popup" to true in ANY of the following cases:
  1. A pop-up overlay, cookie consent banner, GDPR dialog, or advertisement wall dominates the
     page and prevents access to actual content.
  2. The page contains no meaningful financial data relevant to the objective -- only privacy
     notices, cookie policies, terms-of-service, or advertisements with no financial content.
  3. The page is entirely empty or has very short content (<300 chars after stripping whitespace)
     that contains no financial data.
  4. The page is an age-gate, login wall, paywall, or any other access-barrier form.
- Set "has_popup" to false ONLY if the page contains real financial content relevant to the
  objective.

Respond ONLY with a valid JSON object -- no preamble, no explanation outside the JSON.

Schema:
{{{{
  "has_popup":      true | false,
  "transform_script": "<complete, self-contained Python script>",
  "reasoning":        "<1-3 sentences: what data was found and how the script extracts it>"
}}}}

Rules for transform_script:
- Import only Python standard library modules (json, re, sys, csv, io, datetime, etc.).
- Read the full Markdown from sys.stdin (e.g. text = sys.stdin.read()).
- Output exactly ONE JSON object to stdout via print(json.dumps(...)).
- The JSON output schema for the script\'s stdout must be:\n{{output_json_schema}}
- Handle missing or malformed data gracefully -- use empty lists/dicts rather than raising.
- Do NOT make any network calls, file I/O, or subprocess calls.
{{additional_context}}"""

_STUDY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", (
        "Research objective: {objective}\n\n"
        "Source URL: {source_url}\n\n"
        "Page content (Markdown):\n\n{markdown}"
    )),
])


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class StudyWebContentInput(BaseModel):
    """Input for the study_web_content task.

    Attributes:
        markdown:           Markdown text produced by ``html_to_markdown``.
        source_url:         URL of the page (for display).
        objective:          Research question or goal that guides what data to extract.
        output_json_schema: JSON schema dict describing the expected structure of the
                            transform script's stdout JSON.  Injected into the system
                            prompt so the LLM generates a script whose output conforms
                            to the downstream task's input (e.g. ``GetStatsInput``).
        additional_context: Optional list of extra instruction snippets appended to the
                            system prompt.  Callers (e.g. prepare_peers) inject
                            domain-specific extraction rules here instead of embedding
                            them in the base system prompt.
    """

    markdown: str = Field(description="Markdown content of the crawled page.")
    source_url: str = Field(description="URL that was crawled.")
    objective: str = Field(description="Research objective that guides data extraction.")
    output_json_schema: dict = Field(
        description=(
            "JSON schema for the transform script's stdout. "
            "Typically the input schema of the next downstream task (e.g. get_stats)."
        ),
    )
    additional_context: list[str] = Field(
        default_factory=list,
        description=(
            "Extra instruction snippets appended to the system prompt. "
            "Use to inject caller-specific extraction rules without polluting the base prompt."
        ),
    )
    failure_context: str = Field(
        default="",
        description=(
            "Guidance from a prior failed attempt (failure reason + recovery reasoning) "
            "carried by the agent step loop on a regeneration retry.  When set, it is "
            "injected into the prompt so the LLM rewrites the script to fix the issue. "
            "Contains no concrete values -- the LLM must still extract correct data itself."
        ),
    )


class StudyWebContentOutput(BaseModel):
    """Output from the study_web_content task.

    Attributes:
        source_markdown:  The original Markdown passed to the LLM; forwarded as
                          stdin to ``run_sandbox`` when it executes the script.
        transform_script: A stdlib-only Python script that reads Markdown from
                          stdin and prints a single JSON object to stdout.
        reasoning:        LLM's brief rationale for what data was found and how
                          the script extracts it.
        has_popup:        ``True`` when the LLM determined the page is dominated by a
                          cookie-consent / GDPR / advertisement overlay rather than
                          real financial content.  When ``True`` the pipeline triggers
                          ``propose_playwright_script`` -> sandbox execution -> retry.
        from_cache:       ``True`` when served from the ``llm_responses`` prompt-hash cache.
    """

    source_markdown: str = Field(
        description="Original Markdown text forwarded to run_sandbox as stdin.",
    )
    transform_script: str = Field(
        default="",
        description="Python script (stdlib only) that reads Markdown from stdin and prints JSON.",
    )
    reasoning: str = Field(default="", description="LLM reasoning for the extraction approach.")
    has_popup: bool = Field(
        default=False,
        description=(
            "True when the page cannot yield financial data: blocked by a pop-up/consent/GDPR overlay, "
            "contains only privacy/cookie/ads content, is empty/very short, or is any other access barrier. "
            "When True the pipeline triggers propose_playwright_script -> sandbox execution -> retry."
        ),
    )
    from_cache: bool = Field(default=False, description="True when served from llm_responses prompt-hash cache.")


# ---------------------------------------------------------------------------
# Prompt builder (registered in STREAM_PROMPT_BUILDERS)
# ---------------------------------------------------------------------------


def _build_study_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for study_web_content.

    Formats the system prompt with the caller-supplied ``output_json_schema`` and
    injects the research objective, source URL, and page Markdown into the human message.

    Args:
        payload: Serialised :class:`StudyWebContentInput` dict.

    Returns:
        LangChain message list (SystemMessage + HumanMessage).
    """
    import json as _json  # noqa: PLC0415 -- local to avoid top-level shadowing
    inp = StudyWebContentInput.model_validate(payload)

    schema_text = _json.dumps(inp.output_json_schema, indent=2)

    # Truncate very long pages to keep the request within the model's max message
    # tokens (dense/CJK pages tokenize ~1 token per char).  Configurable cap.
    max_chars = get_settings().STUDY_MARKDOWN_MAX_CHARS
    markdown_excerpt = inp.markdown[:max_chars]
    if len(inp.markdown) > max_chars:
        markdown_excerpt += "\n\n[... content truncated for length ...]"

    # Append caller-supplied additional_context snippets to the system prompt.
    additional_context_text = ""
    if inp.additional_context:
        snippets = "\n\n".join(inp.additional_context)
        additional_context_text = f"\n\n{snippets}"

    # On a regeneration retry, prepend the failure guidance so the LLM fixes the
    # prior mistake.  Contains no concrete values -- only the failure reason and
    # recovery reasoning.
    if inp.failure_context:
        additional_context_text += (
            "\n\nPREVIOUS ATTEMPT FAILED -- you MUST address this when rewriting the "
            f"script:\n{inp.failure_context}"
        )

    return _STUDY_PROMPT.format_messages(
        output_json_schema=schema_text,
        additional_context=additional_context_text,
        objective=inp.objective,
        source_url=inp.source_url,
        markdown=markdown_excerpt,
    )


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_study_prompt}

# ---------------------------------------------------------------------------
# PG cache lookup SQL (by prompt_hash + task_name within TTL)
# ---------------------------------------------------------------------------

_GET_CACHED_LLM_RESPONSE = """
    SELECT lr.answer
    FROM fin_agents.llm_responses lr
    WHERE lr.task_name  = %s
      AND lr.prompt_hash = %s
      AND lr.answer      IS NOT NULL
      AND lr.ts          > NOW() - INTERVAL '%s hours'
    ORDER BY lr.ts DESC
    LIMIT 1
"""


# ---------------------------------------------------------------------------
# PG cache function
# ---------------------------------------------------------------------------


async def _study_web_content_pg_cache(
    inp: StudyWebContentInput, ctx: NodeContext
) -> StudyWebContentOutput | None:
    """Check pg for a recent study_web_content result with the same prompt hash.

    Computes the MD5 of the rendered prompt messages and looks up
    ``fin_agents.llm_responses`` for a row with the same ``task_name`` +
    ``prompt_hash`` within the last ``_CACHE_TTL_HOURS`` hours.

    Args:
        inp: Typed task input.
        ctx: Current node context (unused; present for signature compatibility).

    Returns:
        :class:`StudyWebContentOutput` on a cache hit, ``None`` otherwise.
    """
    payload = inp.model_dump(mode="json")
    messages = _build_study_prompt(payload)
    prompt_text = "\n\n".join(
        f"{getattr(m, 'type', 'unknown').upper()}:\n{m.content}"
        for m in messages
        if getattr(m, "content", None)
    )
    prompt_hash = hashlib.md5(prompt_text.encode()).hexdigest()

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            _GET_CACHED_LLM_RESPONSE,
            (_TASK_NAME, prompt_hash, _CACHE_TTL_HOURS),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    try:
        answer_dict: dict = json.loads(row["answer"]) if row.get("answer") else {}
    except (json.JSONDecodeError, TypeError):
        return None
    transform_script = str(answer_dict.get("transform_script", "")).strip()
    if not transform_script:
        return None
    return StudyWebContentOutput(
        source_markdown=inp.markdown,
        transform_script=transform_script,
        reasoning=str(answer_dict.get("reasoning", "")),
        has_popup=bool(answer_dict.get("has_popup", False)),
        from_cache=True,
    )


# ---------------------------------------------------------------------------
# Answer parser
# ---------------------------------------------------------------------------


def _parse_study_answer(
    answer_dict: dict,
    source_markdown: str,
) -> StudyWebContentOutput:
    """Parse and validate the LLM JSON answer into a :class:`StudyWebContentOutput`.

    Args:
        answer_dict:     Parsed JSON dict from the streaming answer.
        source_markdown: Original Markdown from the task input; forwarded as-is.

    Returns:
        Validated :class:`StudyWebContentOutput`.
    """
    return StudyWebContentOutput(
        source_markdown=source_markdown,
        transform_script=str(answer_dict.get("transform_script", "")),
        reasoning=str(answer_dict.get("reasoning", "")),
        has_popup=bool(answer_dict.get("has_popup", False)),
    )


# ---------------------------------------------------------------------------
# LangGraph layer -- @task
# ---------------------------------------------------------------------------


@task
async def _study_web_content_task(
    task_input: TaskInput[StudyWebContentInput],
) -> TaskOutput[StudyWebContentOutput]:
    """LangGraph @task: stream LLM analysis of Markdown web content.

    Creates a Streaming task, delegates to ``run_stream`` via ``delegate_stream``,
    parses the structured JSON answer, and completes the task.  On exception,
    marks the task as failed and re-raises so ``seq.py`` can handle the error.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`StudyWebContentInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`StudyWebContentOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")
    source_markdown: str = task_input.content.markdown

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
        output = _parse_study_answer(result.get("answer", {}), source_markdown)
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


study_web_content: NodeTask[StudyWebContentInput, StudyWebContentOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Streaming LLM task: analyse a crawled page's Markdown content and generate a "
        "stdlib-only Python transform script that reads the Markdown from stdin and prints "
        "a structured financial JSON object to stdout. "
        "Outputs source_markdown (for run_sandbox stdin) and transform_script."
    ),
    input_type=StudyWebContentInput,
    output_type=StudyWebContentOutput,
    task_fn=_study_web_content_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("study_web_content runs via the Celery stream worker.")
    ),
    pg_cache_fn=_study_web_content_pg_cache,
)

HANDLERS: dict = {}

__all__ = [
    "StudyWebContentInput",
    "StudyWebContentOutput",
    "study_web_content",
    "STREAM_PROMPT_BUILDERS",
    "HANDLERS",
]
