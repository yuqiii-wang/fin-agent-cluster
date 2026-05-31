"""PrepareDerivativesNode — Agent node that fetches derivatives market knowledge
and calculates OHLCV stats for the queried equity symbol.

Hierarchy
---------
Thread
  └── prepare_derivatives  (Agent)
        ├── load_markdown  (propose_web_knowledge_urls + load_md_from_url:
        │                   crawl_url + html_to_markdown)
        ├── study_web      (study_web_content + run_sandbox — LLM streaming step)
        └── get_and_calculate_stats  (TaskSeq → get_stats + calculate_stats)

Node design
-----------
The node reads the stock symbol from ``query_node`` output and runs sequential
steps for that symbol:

1. ``load_markdown`` — proposes one or more financial data URLs for the equity
   symbol, then crawls each URL and converts the HTML to Markdown.
2. ``study_web`` — the LLM *streaming* step: generates a Python transform script
   per page and executes it in a sandbox to produce structured options JSON.
   Calls/puts from all pages are merged and deduplicated.  On a later-step
   failure the agent loop regenerates this step with failure-context guidance.
3. ``get_and_calculate_stats`` — ingests the merged options JSON and computes
   technical indicators for the underlying equity symbol; persists rows to
   ``fin_markets.quant_stats``.
3. ``calculate_options`` — upserts each call/put contract into
   ``fin_markets.quant_options_stats`` and aggregates per expiry into
   ``fin_markets.quant_derivative_stats``.

Predecessor
-----------
``query_node`` — must be completed before ``prepare_derivatives`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_macro_stats``, ``prepare_index``,
``prepare_news``, ``prepare_industry_news``, and ``prepare_macro_news``.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar
from uuid import uuid4

from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    get_and_calculate_stats,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculation_utils.calculate_option_stats import (
    calculate_option_stats,
)
from backend.langgraph.models.common_tasks.run_sandbox import run_sandbox
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.seq import (
    load_md_from_url,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.propose_web_knowledge_urls import (
    propose_web_knowledge_urls,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.study_web_content import (
    study_web_content,
)
from backend.langgraph.models.common_tasks.llm_orchestration_on_failure import (
    LlmOrchestrationInput,
    llm_orchestration_on_failure,
)
from backend.langgraph.models.models import NodeContext, TaskContext, TaskOutput
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_derivatives.agent_steps import (
    AGENT_STEPS,
    STEP_ORDER,
    STEP_STUDY_WEB,
    DerivativesStepContext,
)
from backend.langgraph.nodes.prepare_derivatives.models import (
    DerivativesGlobalState,
    PrepareDerivativesInput,
    PrepareDerivativesOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)

_SUMMARY_KEY: str = "__derivatives_summary__"


class PrepareDerivativesNode(BaseNode[PrepareDerivativesInput, PrepareDerivativesOutput]):
    """Workflow node: fetches derivatives web knowledge and calculates OHLCV stats."""

    node_name = "prepare_derivatives"
    node_type = NodeType.AGENT
    display_name = "Prepare Derivatives"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review derivatives analysis",
            "type": "boolean",
            "description": "Pause after derivatives data is fetched; wait for your approval.",
        },
        {
            "key": "stats_period",
            "label": "Stats period",
            "type": "select",
            "options": [
                {"value": "2y", "label": "2 years"},
            ],
            "description": "Lookback period for OHLCV stats calculation.",
        },
    ]
    view_type = "Stats"
    stats_views = ["DerivativesFlow"]
    tasks: ClassVar[list[NodeTask]] = [
        propose_web_knowledge_urls,
        *load_md_from_url.tasks,
        study_web_content,
        run_sandbox,
        *get_and_calculate_stats.tasks,
        calculate_option_stats,
    ]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    # ── Agent step loop configuration ──────────────────────────────────────
    agent_global_state_class: ClassVar[type] = DerivativesGlobalState
    agent_steps: ClassVar[dict] = AGENT_STEPS
    agent_step_order: ClassVar[list[str]] = STEP_ORDER
    agent_streaming_steps: ClassVar[set[str]] = {STEP_STUDY_WEB}
    agent_orchestration_task: ClassVar = llm_orchestration_on_failure
    _agent_max_iterations: ClassVar[int] = 2

    async def build_input(self, state: GraphState) -> PrepareDerivativesInput:
        """Construct node input — reads stock_symbol from query_node output.

        Args:
            state: Current GraphState.

        Returns:
            :class:`PrepareDerivativesInput` with the resolved stock symbol.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_symbol = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_symbol = output.get("stock_name", "")
        if not stock_symbol:
            logger.error("[PD-001] No stock symbol from query_node; prepare_derivatives will skip.")
        return PrepareDerivativesInput(stock_symbol=stock_symbol)

    async def _create_agent_global_state(
        self, node_input: PrepareDerivativesInput
    ) -> DerivativesGlobalState:
        """Initialise global state with the uppercased symbol.

        Args:
            node_input: Typed node input.

        Returns:
            Fresh :class:`DerivativesGlobalState` for this agent run.
        """
        symbol = node_input.stock_symbol.upper() if node_input.stock_symbol else ""
        return DerivativesGlobalState(symbol=symbol)

    def _create_agent_step_state(
        self,
        iteration: int,
        global_state: DerivativesGlobalState,
        failure_context: str,
    ) -> str:
        """Return the per-iteration failure-context guidance for the step loop.

        Args:
            iteration:       Outer iteration counter (1-based).
            global_state:    Cross-iteration global state.
            failure_context: Guidance string from ``llm_orchestration_on_failure``
                             (empty on the first iteration).

        Returns:
            The ``failure_context`` string, passed through to the step context.
        """
        return failure_context

    def _create_step_context(
        self,
        ctx: NodeContext,
        global_state: DerivativesGlobalState,
        step_state: str,
        results: dict[str, TaskOutput],
        node_input: PrepareDerivativesInput,
    ) -> DerivativesStepContext:
        """Assemble the step-context bundle passed to every step function.

        Args:
            ctx:          Current node context.
            global_state: Cross-iteration global state.
            step_state:   Failure-context guidance (empty on first run).
            results:      Accumulated ``TaskOutput`` dict.
            node_input:   Typed node input.

        Returns:
            Populated :class:`DerivativesStepContext`.
        """
        return DerivativesStepContext(
            run_task=self.run_task,
            ctx=ctx,
            g=global_state,
            results=results,
            stats_period=node_input.stats_period,
            failure_context=step_state or "",
        )

    def _build_orchestration_input(
        self,
        global_state: DerivativesGlobalState,
        step_state: str,
        failed_step: str,
        failure_reason: str,
        results: dict[str, TaskOutput],
        iteration: int,
        retry_candidates: list[str],
    ) -> LlmOrchestrationInput:
        """Build the recovery-decision input after a step failure.

        Args:
            global_state:     Cross-iteration global state.
            step_state:       Current iteration failure-context guidance.
            failed_step:      Name of the step that raised.
            failure_reason:   Exception message from the failed step.
            results:          Accumulated ``TaskOutput`` dict.
            iteration:        Current iteration number (1-based).
            retry_candidates: Earlier LLM streaming step names eligible for
                              regeneration.

        Returns:
            Populated :class:`LlmOrchestrationInput`.
        """
        return LlmOrchestrationInput(
            failed_step=failed_step,
            failure_reason=failure_reason,
            objective=(
                "Fetch derivatives market knowledge and compute OHLCV/options "
                "stats for the equity symbol."
            ),
            target=global_state.symbol,
            step_order=list(STEP_ORDER),
            retry_candidates=retry_candidates,
            finish_condition=(
                "Each step produces usable structured output for the symbol "
                "with no unhandled errors."
            ),
            context_summary={"symbol": global_state.symbol, "iteration": iteration},
        )

    async def _build_final_output(
        self,
        global_state: DerivativesGlobalState,
        results: dict[str, TaskOutput],
        node_input: PrepareDerivativesInput,
        ctx: NodeContext,
    ) -> dict[str, TaskOutput]:
        """Build the summary ``TaskOutput`` under ``_SUMMARY_KEY``.

        Args:
            global_state: Cross-iteration global state at loop end.
            results:      Accumulated ``TaskOutput`` values.
            node_input:   Typed node input.
            ctx:          Node context.

        Returns:
            *results* with ``_SUMMARY_KEY`` entry appended.
        """
        g = global_state
        summary_ctx = TaskContext(
            **ctx.model_dump(), task_id=str(uuid4()), task_name=_SUMMARY_KEY
        )
        results[_SUMMARY_KEY] = TaskOutput(
            ctx=summary_ctx,
            content={"symbol": g.symbol},
        )
        return results

    def build_output(self, results: dict[str, TaskOutput]) -> PrepareDerivativesOutput:
        """Compose node output from the agent summary stored under ``_SUMMARY_KEY``.

        Args:
            results: Keyed task outputs from ``build_agent``.

        Returns:
            :class:`PrepareDerivativesOutput` with symbol and web knowledge URL.
        """
        summary = results.get(_SUMMARY_KEY)
        if summary is None:
            raise RuntimeError(
                "PD-005: derivatives summary missing from agent results — "
                "_build_final_output did not complete."
            )
        data: dict = summary.content
        return PrepareDerivativesOutput(
            symbol=data.get("symbol", ""),
        )

    def get_state_updates(self, output: PrepareDerivativesOutput) -> dict[str, Any]:
        """No GraphState updates — output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


# Module-level callable registered with LangGraph StateGraph.
prepare_derivatives_node = PrepareDerivativesNode()
