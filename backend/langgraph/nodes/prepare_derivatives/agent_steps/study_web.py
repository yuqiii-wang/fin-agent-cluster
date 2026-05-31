"""study_web.py — Step 2: LLM-generate extraction scripts and run them in a sandbox."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.langgraph.models.common_tasks.run_sandbox import (
    RunSandboxInput,
    run_sandbox,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.models import (
    LoadMdFromUrlOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.study_web_content import (
    StudyWebContentInput,
    study_web_content,
)
from backend.langgraph.nodes.prepare_derivatives.agent_steps.extraction_schema import (
    ADDITIONAL_CONTEXT,
    DERIVATIVES_OUTPUT_SCHEMA,
    NAVIGATE_OBJECTIVE,
)
from backend.langgraph.nodes.prepare_derivatives.models.state import DerivativesStepContext

logger = logging.getLogger(__name__)


def _merge_options_results(
    sandbox_stdouts: list[str],
    symbol: str,
) -> dict[str, Any] | None:
    """Merge options JSON from all successful sandbox runs.

    Collects calls and puts from all results.  Deduplicates by ``contract_name``
    when the field is present, but includes contracts without it.  Returns
    ``None`` only when no run produced a parseable ``data_type='options'`` response.

    Args:
        sandbox_stdouts: Non-empty stdout strings from successful sandbox runs.
        symbol:          Equity symbol for logging context.

    Returns:
        Merged options dict with ``data_type='options'``, ``calls`` list, and ``puts`` list;
        or ``None`` if no run returned a valid options response.
    """
    seen_call_keys: set[str] = set()
    all_calls: list[dict] = []
    seen_put_keys: set[str] = set()
    all_puts: list[dict] = []
    any_valid_parse = False

    for stdout in sandbox_stdouts:
        try:
            parsed = json.loads(stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("[PD-003f] sandbox stdout JSON parse error symbol=%r: %s", symbol, exc)
            continue

        if "data_type" not in parsed:
            parsed["data_type"] = "options"

        if parsed.get("data_type") != "options":
            logger.error(
                "[PD-003g] unexpected data_type=%r in sandbox output symbol=%r — skipping",
                parsed.get("data_type"),
                symbol,
            )
            continue

        any_valid_parse = True

        for contract in parsed.get("calls") or []:
            key = contract.get("contract_name")
            if key:
                if key not in seen_call_keys:
                    seen_call_keys.add(key)
                    all_calls.append(contract)
            else:
                all_calls.append(contract)

        for contract in parsed.get("puts") or []:
            key = contract.get("contract_name")
            if key:
                if key not in seen_put_keys:
                    seen_put_keys.add(key)
                    all_puts.append(contract)
            else:
                all_puts.append(contract)

    if not any_valid_parse:
        return None

    return {
        "data_type": "options",
        "calls": all_calls,
        "puts": all_puts,
    }


async def _study_and_run(
    sctx: DerivativesStepContext,
    page: LoadMdFromUrlOutput,
    objective: str,
) -> str | None:
    """Generate a transform script for one Markdown page and run it in the sandbox.

    Forwards ``sctx.failure_context`` to ``study_web_content`` so a regeneration
    retry rewrites the script with awareness of the prior failure.

    Args:
        sctx:      Step context (provides ``failure_context``).
        page:      Loaded Markdown page.
        objective: Research objective guiding extraction.

    Returns:
        Sandbox stdout (extracted options JSON string) on success, else ``None``.
    """
    study_result = await sctx.run_task(
        study_web_content,
        sctx.ctx,
        StudyWebContentInput(
            markdown=page.html_to_markdown.markdown,
            source_url=page.crawl_url.url,
            objective=objective,
            output_json_schema=DERIVATIVES_OUTPUT_SCHEMA,
            additional_context=ADDITIONAL_CONTEXT,
            failure_context=sctx.failure_context,
        ),
    )
    study_output = study_result.content

    sandbox_result = await sctx.run_task(
        run_sandbox,
        sctx.ctx,
        RunSandboxInput(
            script=study_output.transform_script,
            language="python",
            stdin=study_output.source_markdown,
        ),
    )
    sandbox = sandbox_result.content
    if sandbox.exit_code != 0 or not sandbox.stdout:
        logger.error(
            "[PD-003] sandbox extraction failed url=%r exit_code=%s",
            page.crawl_url.url,
            sandbox.exit_code,
        )
        return None
    return sandbox.stdout


async def step_study_web(sctx: DerivativesStepContext) -> None:
    """Step 2 (streaming): generate extraction scripts and run them in a sandbox.

    For each Markdown page loaded by ``step_load_markdown``, asks the LLM to
    generate a stdlib-only transform script (``study_web_content``) and executes
    it in the sandbox.  Calls/puts from all pages are merged and deduplicated and
    stored in ``g.json_input`` for downstream steps.

    This is the agent's LLM *streaming* step: when a later step fails, the agent
    loop regenerates it carrying ``sctx.failure_context`` so the script is
    rewritten to fix the issue (the changed prompt bypasses the task cache).

    Raises on failure (no pages, no extractable options) so the agent loop can
    trigger orchestration-driven recovery.

    Args:
        sctx: Step context.

    Raises:
        RuntimeError: When no usable options JSON could be produced.
    """
    g = sctx.g

    if not g.md_pages:
        raise RuntimeError(
            f"[PD-003] no Markdown pages available for study_web step symbol={g.symbol!r}"
        )

    objective = NAVIGATE_OBJECTIVE.format(symbol=g.symbol)

    stdouts: list[str] = []
    for page in g.md_pages:
        stdout = await _study_and_run(sctx, page, objective)
        if stdout is not None:
            stdouts.append(stdout)

    merged = _merge_options_results(stdouts, g.symbol)
    if merged is None:
        raise RuntimeError(
            f"[PD-003h] no valid options JSON (calls/puts) extracted from any URL "
            f"for symbol={g.symbol!r}"
        )

    g.json_input = merged


__all__ = ["step_study_web"]
