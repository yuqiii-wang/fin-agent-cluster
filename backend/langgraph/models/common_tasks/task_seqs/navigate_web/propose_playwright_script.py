"""propose_playwright_script — NodeTask: LLM-stream generation of a Playwright Python script.

When the pipeline encounters a blocked or broken page (popup overlay, consent gate,
access barrier, or crawl error), this task instructs the LLM to write a self-contained
Python script using ``playwright.sync_api`` that:

1. Navigates to the source URL in headless Chromium.
2. Dismisses any overlay or interacts with the page as needed.
3. Captures the final clean HTML and prints it to stdout.

The generated script is intended to be executed directly by ``run_sandbox`` (which has
Playwright installed).  Its stdout is raw HTML, ready to be fed back into
``html_to_markdown``.

Outputs
-------
``playwright_script``
    A standalone Python script that uses ``playwright.sync_api`` to navigate and
    interact with the page and writes the resulting HTML to stdout.

``reasoning``
    LLM's brief explanation of the interaction strategy chosen.

``from_cache``
    ``True`` when the output was served from the ``llm_responses`` prompt-hash cache.

Execution layers
----------------
LangGraph layer (``_propose_playwright_script_task`` decorated with ``@task``):
    Creates a Streaming task, delegates to the Celery stream worker, parses the JSON
    answer, and completes the task.

Celery layer (via ``STREAM_PROMPT_BUILDERS``):
    Dispatched via ``STREAM_PROMPT_BUILDERS`` to ``_build_propose_playwright_prompt``.

Public exports
--------------
``propose_playwright_script``            — ``NodeTask`` instance.
``ProposePlaywrightScriptInput``         — Pydantic input model.
``ProposePlaywrightScriptOutput``        — Pydantic output model.
``STREAM_PROMPT_BUILDERS``               — dict slice for ``stream_task._get_stream_prompt_builders``.
``HANDLERS``                             — empty dict (streaming task; no completion handler).
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
from backend.db.postgres.connection import raw_conn
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.streaming_output import StreamingTaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "propose_playwright_script"
_CACHE_TTL_HOURS = 2

_SYSTEM_PROMPT = """\
You are a web automation engineer.  You will be given:
- A source URL that is currently inaccessible or blocked.
- The raw HTML of the page (which may contain a popup overlay, consent gate, age gate,
  redirect wall, or be partially broken).
- An optional error message from the previous fetch attempt.

Your job is to write a self-contained Python script that uses ``playwright.sync_api`` to:
1. Launch headless Chromium (with ``--no-sandbox``, ``--disable-setuid-sandbox``, \
   ``--disable-dev-shm-usage`` args — required for container environments).
2. Navigate to the source URL and wait for network idle.
3. Identify and dismiss any overlay (cookie consent, GDPR dialog, age gate, ad wall, \
   "I Agree", "Accept All", etc.) by clicking the appropriate element.
4. Wait for the page to stabilise after the interaction (``wait_for_load_state("networkidle")``).
5. Print the full page HTML to stdout via ``print(page.content())``.

IMPORTANT constraints:
- Use ONLY ``playwright.sync_api`` — do NOT use async playwright.
- The script must be fully self-contained and have no imports other than \
  ``from playwright.sync_api import sync_playwright``.
- Do NOT use ``sys``, ``json``, ``os``, or any other imports.
- Handle the case where the dismiss element is not found gracefully by printing \
  the page HTML anyway.
- Use ``page.locator(...).first`` for element selection to avoid strict-mode errors.
- Wrap the element click in a try/except so the script never aborts.
- Set a reasonable timeout: ``page.set_default_timeout(15000)``.

Respond ONLY with a valid JSON object — no preamble, no explanation outside the JSON.

Schema:
{{{{
  "playwright_script": "<full Python source code as a string>",
  "reasoning": "<1-3 sentences: what interaction strategy was chosen and why>"
}}}}"""

_PROPOSE_PLAYWRIGHT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", (
        "Source URL: {source_url}\n\n"
        "Failed error (if any): {failed_err}\n\n"
        "Original HTML (truncated):\n\n{original_html}"
    )),
])


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class ProposePlaywrightScriptInput(BaseModel):
    """Input for the propose_playwright_script task.

    Attributes:
        source_url:    URL of the page that needs Playwright interaction.
        original_html: Raw HTML of the blocked or broken page.
        failed_err:    Error message from the previous fetch attempt, or empty string.
    """

    source_url: str = Field(description="URL of the page to navigate to with Playwright.")
    original_html: str = Field(description="Raw HTML of the blocked or broken page.")
    failed_err: str = Field(
        default="",
        description="Error message from the previous fetch attempt, or empty string.",
    )


class ProposePlaywrightScriptOutput(BaseModel):
    """Output from the propose_playwright_script task.

    Attributes:
        playwright_script: Standalone Python script using playwright.sync_api that
                           navigates the page and prints final HTML to stdout.
        reasoning:         LLM's brief explanation of the interaction strategy.
        from_cache:        True when served from the llm_responses prompt-hash cache.
    """

    playwright_script: str = Field(
        description="Python script (playwright.sync_api) that navigates and prints final HTML to stdout."
    )
    reasoning: str = Field(default="", description="LLM's brief explanation of the strategy chosen.")
    from_cache: bool = Field(default=False, description="True when output was served from PG cache.")


# ---------------------------------------------------------------------------
# Prompt builder (registered in STREAM_PROMPT_BUILDERS)
# ---------------------------------------------------------------------------


def _build_propose_playwright_prompt(payload: dict) -> list[BaseMessage]:
    """Build the LangChain message list for propose_playwright_script.

    Args:
        payload: Serialised :class:`ProposePlaywrightScriptInput` dict.

    Returns:
        LangChain message list (SystemMessage + HumanMessage).
    """
    inp = ProposePlaywrightScriptInput.model_validate(payload)
    html_excerpt = inp.original_html[:12_000]
    if len(inp.original_html) > 12_000:
        html_excerpt += "\n\n[... HTML truncated ...]"
    return _PROPOSE_PLAYWRIGHT_PROMPT.format_messages(
        source_url=inp.source_url,
        failed_err=inp.failed_err or "(none)",
        original_html=html_excerpt,
    )


STREAM_PROMPT_BUILDERS: dict = {_TASK_NAME: _build_propose_playwright_prompt}


# ---------------------------------------------------------------------------
# PG cache lookup SQL
# ---------------------------------------------------------------------------

_GET_CACHED_LLM_RESPONSE = """
    SELECT lr.answer
    FROM fin_agents.llm_responses lr
    WHERE lr.task_name   = %s
      AND lr.prompt_hash = %s
      AND lr.answer      IS NOT NULL
      AND lr.ts          > NOW() - INTERVAL '%s hours'
    ORDER BY lr.ts DESC
    LIMIT 1
"""


async def _propose_playwright_pg_cache(
    inp: ProposePlaywrightScriptInput,
    ctx: NodeContext,
) -> ProposePlaywrightScriptOutput | None:
    """Check the ``llm_responses`` cache for a prior propose_playwright_script result.

    Args:
        inp: Task input.
        ctx: Node context (unused but required by pg_cache_fn signature).

    Returns:
        Cached :class:`ProposePlaywrightScriptOutput` or ``None`` on cache miss.
    """
    messages = _build_propose_playwright_prompt(inp.model_dump(mode="json"))
    prompt_text = " ".join(
        m.content if isinstance(m.content, str) else json.dumps(m.content)
        for m in messages
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
    script = str(answer_dict.get("playwright_script", "")).strip()
    if not script:
        return None
    return ProposePlaywrightScriptOutput(
        playwright_script=script,
        reasoning=str(answer_dict.get("reasoning", "")),
        from_cache=True,
    )


# ---------------------------------------------------------------------------
# Answer parser
# ---------------------------------------------------------------------------


def _parse_propose_playwright_answer(answer_dict: dict) -> ProposePlaywrightScriptOutput:
    """Parse the LLM JSON answer into a :class:`ProposePlaywrightScriptOutput`.

    Args:
        answer_dict: Parsed JSON dict from the streaming answer.

    Returns:
        Validated :class:`ProposePlaywrightScriptOutput`.
    """
    return ProposePlaywrightScriptOutput(
        playwright_script=str(answer_dict.get("playwright_script", "")),
        reasoning=str(answer_dict.get("reasoning", "")),
    )


# ---------------------------------------------------------------------------
# LangGraph layer — @task
# ---------------------------------------------------------------------------


@task
async def _propose_playwright_script_task(
    task_input: TaskInput[ProposePlaywrightScriptInput],
) -> TaskOutput[ProposePlaywrightScriptOutput]:
    """LangGraph @task: stream LLM generation of a Playwright interaction script.

    Args:
        task_input: Typed envelope with context and :class:`ProposePlaywrightScriptInput`.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`ProposePlaywrightScriptOutput`.
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
        output = _parse_propose_playwright_answer(result.get("answer", {}))
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


propose_playwright_script: NodeTask[ProposePlaywrightScriptInput, ProposePlaywrightScriptOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Streaming LLM task: given a blocked or broken page's raw HTML and an optional "
        "error message, generate a self-contained Python script using playwright.sync_api "
        "that navigates to the source URL, dismisses any overlay, and prints final HTML to stdout."
    ),
    input_type=ProposePlaywrightScriptInput,
    output_type=ProposePlaywrightScriptOutput,
    task_fn=_propose_playwright_script_task,
    handler=lambda payload: (_ for _ in ()).throw(
        NotImplementedError("propose_playwright_script runs via the Celery stream worker.")
    ),
    pg_cache_fn=_propose_playwright_pg_cache,
    cache_ttl_seconds=7200,
)

HANDLERS: dict = {}

__all__ = [
    "ProposePlaywrightScriptInput",
    "ProposePlaywrightScriptOutput",
    "propose_playwright_script",
    "STREAM_PROMPT_BUILDERS",
    "HANDLERS",
]
