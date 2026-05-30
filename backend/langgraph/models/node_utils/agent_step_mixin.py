"""agent_step_mixin.py — Generic named-step agent loop mixin for AGENT-type nodes.

Provides
--------
``AgentGlobalStateBase``
    Minimal ``@dataclass`` that all agent global-state classes must extend.
    The runner increments ``iterations_run`` at the start of each outer iteration.

``AgentStepMixin``
    Mixin that adds a generic, LLM-orchestrated step loop to any ``BaseNode``
    subclass with ``node_type == NodeType.AGENT``.

    Class variables to set on the concrete node class:
        ``agent_steps``              — ``dict[str, Callable[..., Awaitable[None]]]``
        ``agent_step_order``         — ordered list of step names
        ``agent_orchestration_task`` — ``NodeTask`` called after each iteration
        ``_agent_max_iterations``    — max outer loop count (default 3)

    Hook methods the concrete class must implement (default raises ``NotImplementedError``):
        ``_create_agent_global_state(node_input) -> AgentGlobalStateBase``
        ``_create_agent_step_state(iteration, global_state, input_overrides) -> Any``
        ``_create_step_context(ctx, global_state, step_state, results, node_input) -> Any``
        ``_build_orchestration_input(global_state, step_state, failed_step, results, iteration) -> Any``
        ``_build_final_output(global_state, results, node_input) -> dict[str, TaskOutput]``

    Optional hook with a no-op default:
        ``_post_iteration_hook(ctx, global_state, step_state, results) -> None``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, ClassVar

if TYPE_CHECKING:
    from backend.langgraph.models.models import NodeContext, TaskOutput
    from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)


@dataclass
class AgentGlobalStateBase:
    """Minimal cross-iteration state required by the generic step runner.

    All agent node global-state dataclasses must extend this so the runner
    can increment ``iterations_run`` without knowing the concrete type.

    Attributes:
        iterations_run: Number of outer iterations completed so far.
    """

    iterations_run: int = 0


class AgentStepMixin:
    """Generic named-step loop mixin for ``NodeType.AGENT`` nodes.

    Mix this into ``BaseNode`` **before** ``ABC`` in the MRO so the default
    ``build_agent`` implementation is available to all concrete agent nodes.
    Concrete nodes that set ``agent_steps`` and ``agent_step_order`` get the
    full loop for free; nodes that need a custom loop can still override
    ``build_agent`` directly.
    """

    agent_steps: ClassVar[dict[str, Callable[..., Awaitable[None]]] | None] = None
    agent_step_order: ClassVar[list[str] | None] = None
    agent_orchestration_task: ClassVar["NodeTask | None"] = None
    agent_global_state_class: ClassVar["type[AgentGlobalStateBase] | None"] = None
    _agent_max_iterations: ClassVar[int] = 3

    async def build_agent(
        self, ctx: "NodeContext", node_input: Any
    ) -> "dict[str, TaskOutput]":
        """Run the named-step loop when ``agent_steps`` is configured.

        Delegates to ``_run_agent_step_loop`` when both ``agent_steps`` and
        ``agent_step_order`` are set; otherwise raises ``NotImplementedError``
        so concrete classes that need a custom loop will be caught early.

        Args:
            ctx:        Node context carrying thread/node/task identity.
            node_input: Typed node input constructed by ``build_input``.

        Returns:
            Keyed ``TaskOutput`` dict produced by ``_build_final_output``.

        Raises:
            NotImplementedError: When ``agent_steps`` is not set and
                ``build_agent`` has not been overridden.
        """
        if self.agent_steps is not None and self.agent_step_order is not None:
            return await self._run_agent_step_loop(ctx, node_input)
        raise NotImplementedError(
            f"{getattr(self, 'node_name', type(self).__name__)!r}: "
            "AGENT node must set agent_steps ClassVar or override build_agent()."
        )

    async def _run_agent_step_loop(
        self, ctx: "NodeContext", node_input: Any
    ) -> "dict[str, TaskOutput]":
        """Generic LLM-orchestrated step loop.

        Iterates up to ``_agent_max_iterations`` times executing steps from
        ``agent_steps`` in ``agent_step_order``.  After each iteration,
        ``agent_orchestration_task`` (when configured) decides the next action:

        * ``"finish"``          — exit early; enough progress was made.
        * ``"fail"``            — unrecoverable; use best-available output.
        * ``"retry_from_step"`` — restart the next iteration from a specific
          step, injecting ``input_overrides`` into the new step state.
        * ``"next_iteration"``  — start a fresh iteration from step 0.

        When ``agent_orchestration_task`` is ``None`` the loop runs all
        iterations unconditionally.

        Args:
            ctx:        Node context.
            node_input: Typed node input.

        Returns:
            Keyed ``TaskOutput`` dict (result of ``_build_final_output``).
        """
        results: dict[str, TaskOutput] = {}
        global_state = await self._create_agent_global_state(node_input)
        step_order: list[str] = self.agent_step_order  # type: ignore[assignment]
        steps: dict[str, Callable] = self.agent_steps  # type: ignore[assignment]

        start_step: str = step_order[0]
        next_input_overrides: dict[str, Any] = {}

        for iteration in range(1, self._agent_max_iterations + 1):
            global_state.iterations_run = iteration
            step_state = self._create_agent_step_state(
                iteration, global_state, next_input_overrides
            )
            next_input_overrides = {}
            sctx = self._create_step_context(
                ctx, global_state, step_state, results, node_input
            )

            failed_step: str | None = None
            start_idx = step_order.index(start_step)
            for step_name in step_order[start_idx:]:
                try:
                    await steps[step_name](sctx)
                except Exception as exc:
                    failed_step = step_name
                    logger.error(
                        "[AP-002] iter=%d step=%s failed: %s", iteration, step_name, exc
                    )
                    break

            # Always reset to first step before orchestration can override it.
            start_step = step_order[0]

            await self._post_iteration_hook(ctx, global_state, step_state, results)

            # Persist iteration snapshot — local import to avoid circular dependency.
            try:
                from backend.langgraph.agent.step_state.ops import upsert_step_state
                from backend.langgraph.agent.step_state.serializer import to_json_safe

                await upsert_step_state(
                    node_id=ctx.node_id,
                    iteration=iteration,
                    global_state=to_json_safe(global_state),
                    step_state=to_json_safe(step_state) if step_state is not None else {},
                )
            except Exception as _persist_exc:
                logger.error(
                    "[AP-010] Failed to persist step state iter=%d node=%s: %s",
                    iteration,
                    ctx.node_id,
                    _persist_exc,
                )

            if self.agent_orchestration_task is None:
                continue

            orch_input = self._build_orchestration_input(
                global_state, step_state, failed_step, results, iteration
            )

            if self._should_skip_orchestration(orch_input):
                break

            if self._should_continue_without_orchestration(orch_input):
                continue

            try:
                orch_out = await self.run_task(  # type: ignore[attr-defined]
                    self.agent_orchestration_task, ctx, orch_input
                )
                results[f"{self.agent_orchestration_task.name}_iter{iteration}"] = orch_out
                decision = orch_out.content
                action: str = getattr(decision, "action", "next_iteration")
            except Exception as orch_exc:
                logger.error(
                    "[AP-007] agent_orchestration_task failed iter=%d: %s",
                    iteration,
                    orch_exc,
                )
                continue  # let outer loop decide next iteration

            if action in ("finish", "fail"):
                if action == "fail":
                    logger.error(
                        "[AP-007] orchestration decided fail iter=%d reasoning=%r",
                        iteration,
                        getattr(decision, "reasoning", ""),
                    )
                break
            elif action == "retry_from_step":
                retry_step: str | None = getattr(decision, "retry_from_step", None)
                if retry_step and retry_step in step_order:
                    start_step = retry_step
                next_input_overrides = getattr(decision, "input_overrides", {}) or {}
            # else "next_iteration": start_step already reset above

        return await self._build_final_output(global_state, results, node_input, ctx)

    # ------------------------------------------------------------------
    # Required hooks — concrete classes must implement all of these
    # ------------------------------------------------------------------

    async def _create_agent_global_state(self, node_input: Any) -> AgentGlobalStateBase:
        """Create the cross-iteration global state for this agent run.

        Args:
            node_input: Typed node input from ``build_input``.

        Returns:
            An ``AgentGlobalStateBase`` subclass instance for this run.

        Raises:
            NotImplementedError: Subclass must implement.
        """
        raise NotImplementedError(
            f"{getattr(self, 'node_name', type(self).__name__)!r} must implement "
            "_create_agent_global_state()."
        )

    def _create_agent_step_state(
        self,
        iteration: int,
        global_state: Any,
        input_overrides: dict[str, Any],
    ) -> Any:
        """Create per-iteration step state (reset each outer loop turn).

        Args:
            iteration:       Current iteration number (1-based).
            global_state:    Populated global state from prior iterations.
            input_overrides: LLM-supplied overrides for individual steps.

        Returns:
            A node-specific step-state instance.

        Raises:
            NotImplementedError: Subclass must implement.
        """
        raise NotImplementedError(
            f"{getattr(self, 'node_name', type(self).__name__)!r} must implement "
            "_create_agent_step_state()."
        )

    def _create_step_context(
        self,
        ctx: Any,
        global_state: Any,
        step_state: Any,
        results: dict,
        node_input: Any,
    ) -> Any:
        """Create the step-context bundle injected into every step function.

        Args:
            ctx:          Node context.
            global_state: Cross-iteration global state.
            step_state:   Current iteration step state.
            results:      Accumulated ``TaskOutput`` dict (mutable).
            node_input:   Typed node input.

        Returns:
            A node-specific step-context instance.

        Raises:
            NotImplementedError: Subclass must implement.
        """
        raise NotImplementedError(
            f"{getattr(self, 'node_name', type(self).__name__)!r} must implement "
            "_create_step_context()."
        )

    def _build_orchestration_input(
        self,
        global_state: Any,
        step_state: Any,
        failed_step: str | None,
        results: dict,
        iteration: int,
    ) -> Any:
        """Build the input model for the ``agent_orchestration_task``.

        Called once per iteration when ``agent_orchestration_task`` is set.

        Args:
            global_state: Cross-iteration global state after step execution.
            step_state:   Current iteration step state.
            failed_step:  Name of the step that raised, or ``None`` on success.
            results:      Accumulated ``TaskOutput`` dict.
            iteration:    Current iteration number (1-based).

        Returns:
            A Pydantic model matching ``agent_orchestration_task.input_type``.

        Raises:
            NotImplementedError: Subclass must implement when
                ``agent_orchestration_task`` is configured.
        """
        raise NotImplementedError(
            f"{getattr(self, 'node_name', type(self).__name__)!r} must implement "
            "_build_orchestration_input()."
        )

    async def _build_final_output(
        self,
        global_state: Any,
        results: dict,
        node_input: Any,
        ctx: Any,
    ) -> dict:
        """Construct and return the final keyed ``TaskOutput`` dict after all iterations.

        Args:
            global_state: Cross-iteration global state at loop end.
            results:      All accumulated ``TaskOutput`` values from the run.
            node_input:   Typed node input (for any final lookups).
            ctx:          Node context (for constructing ``TaskContext`` entries).

        Returns:
            Keyed ``TaskOutput`` dict passed to ``build_output``.

        Raises:
            NotImplementedError: Subclass must implement.
        """
        raise NotImplementedError(
            f"{getattr(self, 'node_name', type(self).__name__)!r} must implement "
            "_build_final_output()."
        )

    def _should_skip_orchestration(self, orch_input: Any) -> bool:
        """Return True to skip the orchestration LLM call and finish immediately.

        Called after building ``orch_input`` but before invoking
        ``agent_orchestration_task``.  When ``True`` the loop breaks with an
        implicit ``"finish"`` action — no streaming LLM round-trip occurs.

        Default is always ``False``.  Override in concrete nodes to short-circuit
        the orchestration call when the iteration outcome is deterministic (e.g.
        all steps succeeded and the exit condition is already met).

        Args:
            orch_input: The orchestration input built by ``_build_orchestration_input``.

        Returns:
            ``True`` to skip the LLM call and break the loop; ``False`` to proceed.
        """
        return False

    def _should_continue_without_orchestration(self, orch_input: Any) -> bool:
        """Return True to skip the orchestration LLM call and continue to the next iteration.

        Checked immediately after ``_should_skip_orchestration`` returns ``False``.
        When ``True`` the orchestration task is not invoked and the outer loop
        advances to the next iteration automatically.

        Default is always ``False`` (run orchestration).  Override in concrete
        nodes to suppress the orchestration round-trip when no step failed and
        the loop should simply proceed without LLM guidance.

        Args:
            orch_input: The orchestration input built by ``_build_orchestration_input``.

        Returns:
            ``True`` to skip the LLM call and continue; ``False`` to proceed.
        """
        return False

    # ------------------------------------------------------------------
    # Optional hook — no-op default, override for side effects
    # ------------------------------------------------------------------

    async def _post_iteration_hook(
        self,
        ctx: Any,
        global_state: Any,
        step_state: Any,
        results: dict,
    ) -> None:
        """Called after each iteration's steps complete, before orchestration.

        Default is a no-op.  Override for per-iteration side effects such as
        writing memory entries or emitting progress notifications.

        Args:
            ctx:          Node context.
            global_state: Cross-iteration global state after this iteration.
            step_state:   This iteration's step state.
            results:      Accumulated ``TaskOutput`` dict.
        """


__all__ = ["AgentGlobalStateBase", "AgentStepMixin"]
