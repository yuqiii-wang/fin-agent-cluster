"""PrepareDerivativesNode — Agent node that fetches derivatives market knowledge
and calculates OHLCV stats for the queried equity symbol.

Hierarchy
---------
Thread
  └── prepare_derivatives  (Agent)
        ├── propose_web_knowledge_urls  — maps symbol to Yahoo Finance options URL
        ├── navigate_web  (TaskSeq → crawl_url + html_to_markdown + study_web_content + run_sandbox)
        └── get_and_calculate_stats  (TaskSeq → get_stats + calculate_stats)

Node design
-----------
The node reads the stock symbol from ``query_node`` output and runs three sequential
steps for that symbol:

1. ``propose_web_knowledge_urls`` — constructs the Yahoo Finance options URL for the
   equity symbol.  No external network call; output feeds directly into step 2.
2. ``navigate_web`` — crawls the proposed URL, converts the HTML to Markdown,
   generates a Python transform script via LLM, and executes it in a sandbox
   to produce structured financial JSON.
3. ``get_and_calculate_stats`` — ingests the sandbox JSON output and computes
   technical indicators for the underlying equity symbol; persists rows to
   ``fin_markets.quant_stats``.

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
from backend.langgraph.models.common_tasks.task_seqs.navigate_web import navigate_web
from backend.langgraph.models.common_tasks.propose_web_knowledge_urls import (
    propose_web_knowledge_urls,
)
from backend.langgraph.models.models import NodeContext, TaskContext, TaskOutput
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_derivatives.agent_steps import (
    AGENT_STEPS,
    STEP_ORDER,
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
                {"value": "1y", "label": "1 year"},
                {"value": "2y", "label": "2 years"},
            ],
            "description": "Lookback period for OHLCV stats calculation.",
        },
    ]
    view_type = "Stats"
    stats_views = ["DerivativesFlow"]
    tasks: ClassVar[list[NodeTask]] = [
        propose_web_knowledge_urls,
        *navigate_web.tasks,
        *get_and_calculate_stats.tasks,
    ]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    # ── Agent step loop configuration ──────────────────────────────────────
    agent_global_state_class: ClassVar[type] = DerivativesGlobalState
    agent_steps: ClassVar[dict] = AGENT_STEPS
    agent_step_order: ClassVar[list[str]] = STEP_ORDER
    agent_orchestration_task: ClassVar = None  # single-iteration; no LLM loop
    _agent_max_iterations: ClassVar[int] = 1

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
        input_overrides: dict,
    ) -> None:
        """No per-iteration step state required for prepare_derivatives.

        Args:
            iteration:       Outer iteration counter (always 1).
            global_state:    Cross-iteration global state.
            input_overrides: Not used (no orchestration).

        Returns:
            ``None``.
        """
        return None

    def _create_step_context(
        self,
        ctx: NodeContext,
        global_state: DerivativesGlobalState,
        step_state: None,
        results: dict[str, TaskOutput],
        node_input: PrepareDerivativesInput,
    ) -> DerivativesStepContext:
        """Assemble the step-context bundle passed to every step function.

        Args:
            ctx:          Current node context.
            global_state: Cross-iteration global state.
            step_state:   ``None`` (unused for prepare_derivatives).
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
            content={"symbol": g.symbol, "web_knowledge_url": g.web_knowledge_url},
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
            web_knowledge_url=data.get("web_knowledge_url", ""),
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
