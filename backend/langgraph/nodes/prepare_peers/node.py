"""AnalyzePeersNode — Agent node that identifies and validates industry peer companies.

Hierarchy
---------
Thread
  └── prepare_peers  (Agent)
        ├── propose_peer_urls           (@task → Celery Streaming)              [×1–3]
        ├── navigate_web                (TaskSeq → crawl+md+study+sandbox)       [×1 per iteration]
        ├── get_and_calculate_stats     (TaskSeq → get_stats + calculate_stats)   [×N per iteration]
        ├── calculate_corr              (@task → Celery Completion)              [×N per iteration]
        ├── analyze_peer_corr           (@task → pure computation)               [×1 per iteration]
        └── peer_orchestration          (@task → Celery Streaming)               [×1 per iteration]

Agent design — LLM-orchestrated step loop
------------------------------------------
Each iteration executes a dict of named steps (``AGENT_STEPS``) in ``STEP_ORDER``.
After every iteration (or mid-iteration failure), ``peer_orchestration`` consults
the LLM to decide the next action:

  * ``"finish"``          — enough peers confirmed; exit early.
  * ``"next_iteration"``  — start a fresh iteration from ``propose_url``.
  * ``"retry_from_step"`` — restart the next iteration from a specific step with
                            LLM-supplied ``input_overrides`` (e.g. custom URL, peer list).
  * ``"fail"``            — no recovery possible; use best-available peers.

After the loop the top ``_MAX_CONFIRMED_PEERS`` confirmed peers by abs(r) are
selected.  If no peer met the threshold the best available are returned
(fallback: top ``_MIN_FALLBACK_PEERS``).

Predecessor
-----------
``query_node`` — must be completed before ``prepare_peers`` starts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from backend.db.postgres.types import NodeType
from backend.langgraph.agent.memory.ops import append_memory_entry, get_max_seq_num
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.common_tasks import calculate_corr
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    get_and_calculate_stats,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web import navigate_web
from backend.langgraph.models.models import NodeContext, TaskContext, TaskOutput
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_peers.agent_steps import (
    AGENT_STEPS,
    STEP_ORDER,
    IterationStepState,
    StepRunContext,
)
from backend.langgraph.nodes.prepare_peers.models import (
    AgentGlobalState,
    AnalyzePeersInput,
    AnalyzePeersOutput,
)
from backend.langgraph.nodes.prepare_peers.tasks.analyze_peer_corr import analyze_peer_corr
from backend.langgraph.nodes.prepare_peers.tasks.peer_orchestration import (
    PeerOrchestrationInput,
    TopCorrPeer,
    peer_orchestration,
)
from backend.langgraph.nodes.prepare_peers.tasks.propose_peer_urls import propose_peer_urls
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loop constants
# ---------------------------------------------------------------------------

_MAX_ITERATIONS: int = 3
# Number of confirmed peers required to exit the loop early.
_MIN_CONFIRMED_TO_EXIT: int = 2
# Max peers to keep in final output.
_MAX_CONFIRMED_PEERS: int = 5
# Minimum peers to return even when none reach the corr threshold (fallback).
_MIN_FALLBACK_PEERS: int = 3
# Summary key in the results dict that carries loop metadata to build_output.
_SUMMARY_KEY: str = "__peer_validation_summary__"

# JSON schema injected into navigate_web / study_web_content so the transform
# script's stdout JSON has a ``peers`` list of ticker symbols.
_PEERS_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "peers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of equity ticker symbols of peer/comparable companies.",
        },
        "industry": {
            "type": "string",
            "description": "Primary industry sector of the target company.",
        },
    },
    "required": ["peers", "industry"],
}

_PEER_DISCOVERY_OBJECTIVE = (
    "Identify the peer or comparable companies for the target stock {stock_name} shown on "
    "this page. Find their FULL COMPANY NAMES as written in the text (e.g. 'Microsoft', "
    "'Amazon', 'Alphabet'). Map each found company name to its primary exchange ticker "
    "symbol. Only include companies clearly mentioned as peers or competitors — do not "
    "invent or guess companies not present in the page."
)

_PEERS_EXTRACTION_SKILL: str = (
    Path(__file__).parent / "skills" / "get_peers.md"
).read_text(encoding="utf-8")


class AnalyzePeersNode(BaseNode[AnalyzePeersInput, AnalyzePeersOutput]):
    """Agent node: proposes and corr-validates industry peer companies for a target stock."""

    node_name = "prepare_peers"
    node_type = NodeType.AGENT
    display_name = "Analyze Peers"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "human_in_the_loop",
            "label": "Review peer analysis",
            "type": "boolean",
            "description": "Pause after peer identification and correlation validation; wait for your approval.",
        },
        {
            "key": "depth",
            "label": "Research depth",
            "type": "select",
            "options": [
                {"value": "shallow", "label": "Shallow — fast overview"},
                {"value": "normal", "label": "Normal — balanced"},
                {"value": "deep", "label": "Deep — thorough"},
            ],
            "description": "Controls how many peer candidates are evaluated per iteration.",
        },
        {
            "key": "max_iterations",
            "label": "Max agent iterations",
            "type": "number",
            "min": 1,
            "max": 5,
            "step": 1,
            "description": "Maximum corr-validation loop iterations for peer identification.",
        },
    ]
    view_type = "Stats"
    tasks: ClassVar[list[NodeTask]] = [
        propose_peer_urls,
        *navigate_web.tasks,
        *get_and_calculate_stats.tasks,
        calculate_corr,
        analyze_peer_corr,
        peer_orchestration,
    ]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    # ── Agent step loop configuration ──────────────────────────────────────
    agent_global_state_class: ClassVar[type] = AgentGlobalState
    agent_steps: ClassVar[dict] = AGENT_STEPS
    agent_step_order: ClassVar[list[str]] = STEP_ORDER
    agent_orchestration_task: ClassVar[NodeTask] = peer_orchestration
    _agent_max_iterations: ClassVar[int] = _MAX_ITERATIONS

    async def build_input(self, state: GraphState) -> AnalyzePeersInput:
        """Read stock_name from query_node's completed node_executions row.

        Args:
            state: Current GraphState.

        Returns:
            Typed ``AnalyzePeersInput`` populated from the PG replica.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_name = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_name = output.get("stock_name", "")
        return AnalyzePeersInput(stock_name=stock_name)

    async def _create_agent_global_state(
        self, node_input: AnalyzePeersInput
    ) -> AgentGlobalState:
        """Initialise cross-iteration state with the uppercased target ticker.

        Args:
            node_input: Typed node input containing the raw stock name.

        Returns:
            Fresh ``AgentGlobalState`` for this agent run.
        """
        return AgentGlobalState(target=node_input.stock_name.upper())

    def _create_agent_step_state(
        self,
        iteration: int,
        global_state: AgentGlobalState,
        input_overrides: dict,
    ) -> IterationStepState:
        """Reset per-iteration state for *iteration*.

        Args:
            iteration:       Current outer iteration counter (1-based).
            global_state:    Cross-iteration state (not mutated here).
            input_overrides: LLM-supplied overrides forwarded from orchestration.

        Returns:
            Fresh ``IterationStepState`` for this iteration.
        """
        return IterationStepState(iteration=iteration, input_overrides=input_overrides)

    def _create_step_context(
        self,
        ctx: NodeContext,
        global_state: AgentGlobalState,
        step_state: IterationStepState,
        results: dict[str, TaskOutput],
        node_input: AnalyzePeersInput,
    ) -> StepRunContext:
        """Assemble the ``StepRunContext`` bundle passed to every step function.

        Args:
            ctx:          Current node context.
            global_state: Cross-iteration global state.
            step_state:   This iteration's step state.
            results:      Accumulated ``TaskOutput`` dict (mutable reference).
            node_input:   Typed node input.

        Returns:
            Populated ``StepRunContext``.
        """
        return StepRunContext(
            run_task=self.run_task,
            ctx=ctx,
            g=global_state,
            s=step_state,
            results=results,
            stock_name=node_input.stock_name,
            peers_output_schema=_PEERS_OUTPUT_SCHEMA,
            peer_discovery_objective=_PEER_DISCOVERY_OBJECTIVE,
            peers_extraction_skill=_PEERS_EXTRACTION_SKILL,
        )

    def _build_orchestration_input(
        self,
        global_state: AgentGlobalState,
        step_state: IterationStepState,
        failed_step: str | None,
        results: dict[str, TaskOutput],
        iteration: int,
    ) -> PeerOrchestrationInput:
        """Build input for the ``peer_orchestration`` LLM task.

        Args:
            global_state: Cross-iteration state after this iteration's steps.
            step_state:   This iteration's step state.
            failed_step:  Name of the failing step, or ``None`` when all succeeded.
            results:      Accumulated ``TaskOutput`` dict.
            iteration:    Current iteration number.

        Returns:
            Populated ``PeerOrchestrationInput``.
        """
        g, s = global_state, step_state
        seen: set[str] = set()
        unique_confirmed = [
            sym
            for sym in g.all_confirmed
            if not (sym in seen or seen.add(sym))  # type: ignore[func-returns-value]
        ]
        failure_reason = (
            s.step_results[failed_step].failure_reason
            if failed_step and failed_step in s.step_results
            else None
        )
        return PeerOrchestrationInput(
            iteration=iteration,
            target=g.target,
            confirmed_count=len(unique_confirmed),
            excluded_url_count=len(g.excluded_urls),
            excluded_peer_count=len(g.excluded_peers),
            step_results=list(s.step_results.values()),
            failed_step=failed_step,
            failure_reason=failure_reason,
            top_corr_peers=[
                TopCorrPeer(symbol=sym, corr=round(v, 4))
                for sym, v in sorted(
                    g.all_peer_corr.items(), key=lambda x: x[1], reverse=True
                )[:5]
            ],
            min_confirmed_to_exit=_MIN_CONFIRMED_TO_EXIT,
            max_iterations=_MAX_ITERATIONS,
        )

    async def _post_iteration_hook(
        self,
        ctx: NodeContext,
        global_state: AgentGlobalState,
        step_state: IterationStepState,
        results: dict[str, TaskOutput],
    ) -> None:
        """Append per-iteration peer corr scores to agent memory.

        Args:
            ctx:          Node context.
            global_state: Cross-iteration global state.
            step_state:   This iteration's step state.
            results:      Accumulated ``TaskOutput`` dict (not mutated here).
        """
        s = step_state
        if s.apc_output is None:
            return
        mem_entries = [
            {
                "symbol": sym,
                "corr": round(corr_val, 4),
                "status": (
                    "confirmed" if sym in s.apc_output.confirmed_peers else "rejected"
                ),
            }
            for sym, corr_val in s.apc_output.peer_corr_scores.items()
        ]
        self.update_agent_memory(ctx, mem_entries)
        seq_num = await get_max_seq_num(ctx.node_id) + 1
        await append_memory_entry(
            ctx.thread_id,
            ctx.node_id,
            "task_result",
            {
                "tool_name": "analyze_peer_corr",
                "result": {
                    "iteration": s.iteration,
                    "confirmed_peers": s.apc_output.confirmed_peers,
                    "rejected_peers": s.apc_output.rejected_peers,
                    "corr_scores": {
                        sym: round(v, 4)
                        for sym, v in s.apc_output.peer_corr_scores.items()
                    },
                },
            },
            seq_num,
        )

    async def _build_final_output(
        self,
        global_state: AgentGlobalState,
        results: dict[str, TaskOutput],
        node_input: AnalyzePeersInput,
        ctx: NodeContext,
    ) -> dict[str, TaskOutput]:
        """Select top peers and build the summary ``TaskOutput`` under ``_SUMMARY_KEY``.

        Picks up to ``_MAX_CONFIRMED_PEERS`` confirmed peers sorted by abs(r).
        Falls back to ``_MIN_FALLBACK_PEERS`` best-available peers when none
        reached the corr threshold.

        Args:
            global_state: Cross-iteration global state at loop end.
            results:      All accumulated ``TaskOutput`` values.
            node_input:   Typed node input (used to access the raw stock name).

        Returns:
            *results* dict with ``_SUMMARY_KEY`` entry appended.
        """
        g = global_state
        target = g.target

        seen: set[str] = set()
        unique_confirmed = [
            sym
            for sym in g.all_confirmed
            if not (sym in seen or seen.add(sym))  # type: ignore[func-returns-value]
        ]
        confirmed = sorted(
            unique_confirmed, key=lambda sym: g.all_peer_corr.get(sym, 0.0), reverse=True
        )
        confirmed = confirmed[:_MAX_CONFIRMED_PEERS]

        if not confirmed:
            logger.error(
                "[prepare_peers] no peer reached corr threshold after %d iterations; "
                "using best available. all_peer_corr=%s",
                g.iterations_run,
                g.all_peer_corr,
            )
            sorted_all = sorted(g.all_peer_corr.items(), key=lambda x: x[1], reverse=True)
            confirmed = [sym for sym, _ in sorted_all[:_MIN_FALLBACK_PEERS]]

        all_syms_ordered = [target] + [p for p in confirmed if p != target]
        peer_df_splits = [
            {"symbol": sym, "label": sym, "df_split": g.df_split_map[sym]}
            for sym in all_syms_ordered
            if sym in g.df_split_map and g.df_split_map[sym]
        ]

        _CORR_COLS = ["close_corr", "sma_20_corr", "sma_50_corr", "ema_12_corr", "ema_26_corr"]
        corr_rows: list[list] = []
        corr_index: list[str] = []
        for sym in confirmed:
            detail = g.all_corr_detail.get(sym, {})
            corr_rows.append([detail.get(col) for col in _CORR_COLS])
            corr_index.append(sym)
        avail_cols = [
            col
            for col in _CORR_COLS
            if corr_rows
            and any(row[_CORR_COLS.index(col)] is not None for row in corr_rows)
        ]
        col_indices = [_CORR_COLS.index(c) for c in avail_cols]
        corr_df_split: dict = (
            {
                "index": corr_index,
                "columns": avail_cols,
                "data": [[row[i] for i in col_indices] for row in corr_rows],
            }
            if corr_index
            else {}
        )

        summary_task_ctx = TaskContext(
            **ctx.model_dump(),
            task_id=str(uuid4()),
            task_name=_SUMMARY_KEY,
        )
        results[_SUMMARY_KEY] = TaskOutput(
            ctx=summary_task_ctx,
            content={
                "industry": g.industry,
                "confirmed_peers": confirmed,
                "peer_correlations": g.all_peer_corr,
                "iterations_run": g.iterations_run,
                "df_splits": peer_df_splits,
                "corr_df_split": corr_df_split,
            },
        )
        return results

    def build_output(self, results: dict[str, TaskOutput]) -> AnalyzePeersOutput:
        """Compose node output from the loop summary stored under ``_SUMMARY_KEY``.

        Args:
            results: Keyed task outputs from ``build_agent``.

        Returns:
            ``AnalyzePeersOutput`` with validated peers, corr scores, and iteration count.
        """
        summary = results.get(_SUMMARY_KEY)
        if summary is None:
            raise RuntimeError(
                "AP-003: peer validation summary missing from agent results — "
                "build_agent did not complete successfully."
            )
        data: dict = summary.content
        return AnalyzePeersOutput(
            df_splits=data.get("df_splits", []),
            corr_df_split=data.get("corr_df_split", {}),
        )

    def get_state_updates(self, output: AnalyzePeersOutput) -> dict[str, Any]:
        """No GraphState updates — output stored in node_executions via lifecycle.

        Args:
            output: Completed node output.

        Returns:
            Empty dict.
        """
        return {}


# Module-level callable registered with LangGraph StateGraph.
prepare_peers_node = AnalyzePeersNode()
