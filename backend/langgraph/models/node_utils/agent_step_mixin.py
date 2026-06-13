"""agent_step_mixin.py -- Generic named-step agent loop mixin for AGENT-type nodes.

Provides
--------
``AgentGlobalStateBase``
    Minimal ``@dataclass`` that all agent global-state classes must extend.
    The runner increments ``iterations_run`` at the start of each outer iteration.

``AgentStepMixin``
    Mixin that adds a generic, LLM-orchestrated step loop to any ``BaseNode``
    subclass with ``node_type == NodeType.AGENT``.

    Class variables to set on the concrete node class:
        ``agent_steps``              -- ``dict[str, Callable[..., Awaitable[None]]]``
        ``agent_step_order``         -- ordered list of step names
        ``agent_streaming_steps``    -- set of step names that wrap an LLM streaming
                                       task and can be regenerated on failure
        ``agent_orchestration_task`` -- ``NodeTask`` called after each iteration
        ``_agent_max_iterations``    -- max outer loop count (default 3)

    Hook methods the concrete class must implement (default raises ``NotImplementedError``):
        ``_create_agent_global_state(node_input) -> AgentGlobalStateBase``
        ``_create_agent_step_state(iteration, global_state, failure_context) -> Any``
        ``_create_step_context(ctx, global_state, step_state, results, node_input) -> Any``
        ``_build_orchestration_input(global_state, step_state, failed_step, failure_reason, results, iteration, retry_candidates) -> Any``
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
    agent_streaming_steps: ClassVar[set[str] | None] = None
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
        """Generic failure-driven step loop.

        Runs steps from ``agent_steps`` in ``agent_step_order``.  An iteration
        succeeds (and the loop exits) once every remaining step completes
        without raising.  When a step raises and retry budget remains,
        ``agent_orchestration_task`` (when configured) studies the failure and
        decides:

        * ``"retry_from_step"`` -- regenerate an earlier LLM *streaming* step
          (chosen from ``agent_streaming_steps`` that run at or before the failed
          step).  No concrete values are injected; instead a ``failure_context``
          string (failure reason + the decision's reasoning) is carried into the
          next iteration's step state so the streaming step's task regenerates
          its output with awareness of the failure.
        * ``"fail"``            -- unrecoverable; use best-available output.

        When ``agent_orchestration_task`` is ``None``, or no earlier streaming
        step exists to regenerate, the loop stops at the first failure and builds
        output from whatever succeeded.

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
        streaming_steps: set[str] = set(self.agent_streaming_steps or set())

        start_step: str = step_order[0]
        next_failure_context: str = ""

        for iteration in range(1, self._agent_max_iterations + 1):
            global_state.iterations_run = iteration
            step_state = self._create_agent_step_state(
                iteration, global_state, next_failure_context
            )
            next_failure_context = ""
            sctx = self._create_step_context(
                ctx, global_state, step_state, results, node_input
            )

            failed_step: str | None = None
            failure_reason: str = ""
            start_idx = step_order.index(start_step)
            for step_name in step_order[start_idx:]:
                try:
                    await steps[step_name](sctx)
                except Exception as exc:
                    failed_step = step_name
                    failure_reason = str(exc)
                    logger.error(
                        "[AP-002] iter=%d step=%s failed: %s", iteration, step_name, exc
                    )
                    break

            # Reset to the first step; orchestration may override below.
            start_step = step_order[0]

            # All steps succeeded -- the iteration is done.
            if failed_step is None:
                break

            # Earlier (or equal) LLM streaming steps that can be regenerated.
            failed_idx = step_order.index(failed_step)
            retry_candidates = [
                s for s in step_order[: failed_idx + 1] if s in streaming_steps
            ]

            # No recovery configured, no candidate to regenerate, or no budget.
            if (
                self.agent_orchestration_task is None
                or not retry_candidates
                or iteration >= self._agent_max_iterations
            ):
                break

            # A step failed and retries remain -- ask the orchestration task to
            # study the failure and pick an earlier streaming step to regenerate.
            orch_input = self._build_orchestration_input(
                global_state, step_state, failed_step, failure_reason,
                results, iteration, retry_candidates,
            )
            try:
                orch_out = await self.run_task(  # type: ignore[attr-defined]
                    self.agent_orchestration_task, ctx, orch_input
                )
            except Exception as orch_exc:
                logger.error(
                    "[AP-007] agent_orchestration_task failed iter=%d: %s",
                    iteration,
                    orch_exc,
                )
                break

            results[f"{self.agent_orchestration_task.name}_iter{iteration}"] = orch_out
            decision = orch_out.content
            action: str = getattr(decision, "action", "fail")

            if action == "retry_from_step":
                retry_step: str | None = getattr(decision, "retry_from_step", None)
                if not retry_step or retry_step not in retry_candidates:
                    logger.error(
                        "[AP-007] orchestration retry_from_step=%r not a valid candidate "
                        "%r iter=%d -- stopping",
                        retry_step,
                        retry_candidates,
                        iteration,
                    )
                    break
                start_step = retry_step
                next_failure_context = self._compose_failure_context(
                    failed_step, failure_reason, orch_out
                )
            else:
                if action == "fail":
                    logger.error(
                        "[AP-007] orchestration decided fail iter=%d reasoning=%r",
                        iteration,
                        getattr(decision, "reasoning", ""),
                    )
                break

        return await self._build_final_output(global_state, results, node_input, ctx)

    @staticmethod
    def _compose_failure_context(
        failed_step: str, failure_reason: str, orch_out: Any
    ) -> str:
        """Compose the failure-context guidance carried to a regenerated streaming step.

        Carries only the failure reason and the orchestration's reasoning/thinking;
        never any concrete corrected values (avoids hallucinated data).

        Args:
            failed_step:    Name of the step that raised.
            failure_reason: Exception message from the failed step.
            orch_out:       ``TaskOutput`` from the orchestration task (provides
                            ``content.reasoning`` and ``thinking``).

        Returns:
            A human-readable guidance string for the streaming task's prompt.
        """
        decision = getattr(orch_out, "content", None)
        reasoning = str(getattr(decision, "reasoning", "") or "")
        thinking = str(getattr(orch_out, "thinking", "") or "")
        parts = [
            f"A later pipeline step '{failed_step}' failed with this error:",
            failure_reason.strip(),
        ]
        if reasoning:
            parts += ["", "Recovery analysis:", reasoning.strip()]
        if thinking:
            parts += ["", "Additional reasoning:", thinking.strip()]
        parts += [
            "",
            "Regenerate your output to fix this. Extract correct values from the "
            "source content -- do NOT invent or hallucinate any numbers or fields.",
        ]
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Required hooks -- concrete classes must implement all of these
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
        failure_context: str,
    ) -> Any:
        """Create per-iteration step state (reset each outer loop turn).

        Args:
            iteration:       Current iteration number (1-based).
            global_state:    Populated global state from prior iterations.
            failure_context: Guidance string (failure reason + orchestration
                             reasoning) to forward to the regenerated streaming
                             step; empty on the first iteration.

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
        failed_step: str,
        failure_reason: str,
        results: dict,
        iteration: int,
        retry_candidates: list[str],
    ) -> Any:
        """Build the input model for the ``agent_orchestration_task``.

        Called only when a step raised, retry budget remains, and at least one
        earlier streaming step exists to regenerate.

        Args:
            global_state:     Cross-iteration global state after step execution.
            step_state:       Current iteration step state.
            failed_step:      Name of the step that raised.
            failure_reason:   Exception message from the failed step.
            results:          Accumulated ``TaskOutput`` dict.
            iteration:        Current iteration number (1-based).
            retry_candidates: Earlier LLM streaming step names eligible for
                              regeneration; ``retry_from_step`` must be one.

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


__all__ = ["AgentGlobalStateBase", "AgentStepMixin"]
