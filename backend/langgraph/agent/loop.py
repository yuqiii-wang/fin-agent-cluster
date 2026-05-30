"""ReAct agent loop for AGENT-type nodes.

The loop:
1. Prepends a system message with node skills and prior memory context.
2. Checks the Redis pause flag before invoking; raises ``AgentPausedError``
   (auto-resume aware) so the entrypoint can gracefully pause.
3. Runs a standard ReAct bind-tools / invoke cycle: LLM is called with the
   current message list; any tool_calls in the response are dispatched
   sequentially; ToolMessages are appended; the cycle repeats until the
   model emits a final text response or ``max_iterations`` is exhausted.
4. Each tool call populates the ``collected`` sink (via ``NodeTask.as_tool``
   side-effects) so downstream ``build_output`` receives ``TaskOutput`` values.
5. Persists the initial user message and the final agent response to
   ``fin_agents.agent_memory`` for UI display.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.langgraph.models.models import NodeContext

logger = logging.getLogger(__name__)

# ========================================================================== #
# Progressive context-assembly helpers
#
# Mirrors two proven patterns:
#  • Claude Code's CLAUDE.md hierarchy — global → project → subdir — where
#    each tier adds more-specific context, oldest/condensed content first.
#  • deepagents' middleware chain — general → specific (summarization →
#    skills → tools → LLM) — surfacing tool descriptions so the LLM can
#    route itself before making any call.
# ========================================================================== #

# Character budget for the memory section of the system prompt.
# ~4 chars/token → 3 200 chars ≈ 800 tokens, leaves ample room for the
# tool schemas that are also appended by bind_tools.
_MEMORY_CHAR_BUDGET = 3200

# Auto-compact when non-summary active entries exceed this count.
_COMPACT_THRESHOLD = 10

# Display priority for memory entry types.
# Lower number = shown first / kept when budget is tight.
# Mirrors deepagents: "intent + artifacts" kept; granular call args dropped.
_MEM_PRIORITY: dict[str, int] = {
    "compacted_summary": 0,  # condensed prior work — always shown (already small)
    "task_result":       1,  # what the tool returned — highest continuity value
    "skill_applied":     2,  # which skill was active when result was produced
    "reasoning":         3,  # model's own conclusions
    "tool_call":         4,  # granular call args — lowest priority, truncated first
}


def _entry_text(content: dict[str, Any]) -> str:
    """Extract a readable one-line summary from a memory entry content dict."""
    if "text" in content:
        return str(content["text"])
    if "summary" in content:
        return str(content["summary"])
    if "tool_name" in content and "result" in content:
        return f"{content['tool_name']} → {str(content['result'])[:200]}"
    if "tool_name" in content and "args" in content:
        return f"called {content['tool_name']}({content['args']})"
    # Streaming task_result format: {answer_json_str: thinking_text}
    if len(content) == 1:
        answer_key, thinking_val = next(iter(content.items()))
        return f"answer: {str(answer_key)[:200]} | thinking: {str(thinking_val)[:200]}"
    return str(content)[:200]


def _build_memory_section(entries: list[Any]) -> str:
    """Build the tiered memory context section respecting *_MEMORY_CHAR_BUDGET*.

    Assembly order mirrors Claude Code's hierarchy: oldest condensed context
    (``compacted_summary``) shown first; remaining budget filled by
    ``task_result`` → ``reasoning`` → ``tool_call``, newest within each tier.
    """
    if not entries:
        return ""

    summaries = [e for e in entries if e.entry_type == "compacted_summary"]
    rest = sorted(
        [e for e in entries if e.entry_type != "compacted_summary"],
        key=lambda e: (_MEM_PRIORITY.get(e.entry_type, 99), -e.seq_num),
    )

    lines: list[str] = []
    budget = _MEMORY_CHAR_BUDGET

    # compacted_summaries are always included; they are already condensed.
    for entry in summaries:
        text = _entry_text(entry.content)[:500]
        line = f"[Prior summary] {text}"
        lines.append(line)
        budget -= len(line) + 1

    # Fill remaining budget with priority-ordered entries (newest first per tier).
    for entry in rest:
        if budget <= 100:
            break
        label = entry.entry_type.replace("_", " ").title()
        line = f"[{label}] {_entry_text(entry.content)[:300]}"
        if len(line) <= budget:
            lines.append(line)
            budget -= len(line) + 1

    return "\n".join(lines)


def _build_system_context(
    base_prompt: str,
    tools: list[Any],
    skills: list[Any],
    memory_entries: list[Any],
) -> str:
    """Assemble the tiered system context for the ReAct agent.

    Tiers follow the deepagents general→specific chain and Claude Code's
    CLAUDE.md scope hierarchy:

    Tier 1 — Role / domain  (``base_prompt`` — most general, always first)
    Tier 2 — Tool catalogue (descriptions act as a routing guide; LLM learns
              *when* to call each tool, not just *what* schema it accepts)
    Tier 3 — User skills    (newest-first so the most recently specified
              intent sits closest to the task message, maximising attention)
    Tier 4 — Prior execution memory  (compacted_summary → task_result →
              reasoning; budget-limited, oldest condensed context first)
    """
    sections: list[str] = [base_prompt.rstrip()]

    # Tier 2: tool catalogue.
    if tools:
        tool_lines = "\n".join(f"- **{t.name}**: {t.description}" for t in tools)
        sections.append(
            "## Available tools\n"
            "Always call the appropriate tool to retrieve real-time data — "
            "never answer from your own training knowledge.\n"
            + tool_lines
        )

    # Tier 3: user skills — newest-first (reversed) so the most recently
    # added instruction has the highest LLM attention weight.
    if skills:
        skill_lines = "\n".join(f"- {s.instructions}" for s in reversed(skills))
        sections.append(f"## User instructions\n{skill_lines}")

    # Tier 4: prior execution memory (tiered, budget-limited).
    mem_text = _build_memory_section(memory_entries)
    if mem_text:
        sections.append(f"## Prior execution context\n{mem_text}")

    return "\n\n".join(sections)


async def run_agent_loop(
    node: Any,
    ctx: "NodeContext",
    system_prompt: str,
    user_message: str,
    *,
    max_iterations: int = 20,
) -> dict[str, Any]:
    """Drive a ReAct tool-calling agent and return keyed ``TaskOutput`` results.

    Implements a standard bind-tools → invoke → dispatch-tool-calls loop using
    the node's ``NodeTask`` registry.  The LLM is stepped through up to
    ``max_iterations`` rounds; the loop exits early once the model emits a
    response with no pending tool_calls.

    - Skills stored in ``fin_agents.agent_skills`` are appended to the system
      prompt so the LLM is aware of user-defined guidance.
    - Prior active memory entries are injected as system context so the agent
      can reason over previously completed steps on resume.
    - The Redis pause flag is checked once before invoking the agent; if set
      an ``AgentPausedError`` is raised with the correct ``auto_resume`` value.
    - Each tool call populates *collected* via ``NodeTask.as_tool`` side-effects.
    - The initial user message and final agent response are persisted to
      ``fin_agents.agent_memory`` for UI display.

    Args:
        node:           The ``BaseNode`` instance owning ``run_task`` and
                        ``tasks`` (used to create ``StructuredTool`` wrappers).
        ctx:            ``NodeContext`` carrying thread/node identity.
        system_prompt:  Base instruction string for the LLM.
        user_message:   Initial human turn message describing the task goal.
        max_iterations: Maximum bind-tools rounds before the loop exits.

    Returns:
        Dict mapping each executed task name to its ``TaskOutput``.

    Raises:
        AgentPausedError: When the Redis pause flag is detected before
                          invoking; caller (``EntrypointMixin``) handles
                          pause → optional auto-resume flow.
    """
    import json as _json

    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    from backend.langgraph.agent.capabilities import resolve_capabilities
    from backend.langgraph.agent.errors import AgentPausedError
    from backend.langgraph.agent.memory.ops import (
        append_memory_entry,
        compact_if_needed,
        get_max_seq_num,
        get_memory_entries,
    )
    from backend.langgraph.agent.pause import is_agent_auto_resume_set, is_agent_pause_flag_set
    from backend.langgraph.agent.skills.ops import copy_skills_from_node, get_skills
    from backend.langgraph.agent.tools import get_tool_infos_for_tasks
    from backend.llm.factory import get_llm

    node_id = ctx.node_id
    thread_id = ctx.thread_id

    # --------------------------------------------------------------------- #
    # On re-explore: inherit active skills from the previous version's node.
    # Memory is NOT copied — the new branch intentionally starts fresh.
    # This runs only on the first iteration (skills still empty for this
    # new node_id) to avoid double-copying on pause+resume cycles.
    # --------------------------------------------------------------------- #
    if ctx.version > 1:
        from backend.db.postgres import raw_conn as _raw_conn
        from backend.langgraph.lifecycle.ids import make_node_id as _make_node_id

        existing_skills = await get_skills(node_id, active_only=True)
        if not existing_skills:
            async with _raw_conn(readonly=True) as _conn:
                _cur = await _conn.execute(
                    """
                    SELECT node_id, version
                    FROM fin_agents.nodes
                    WHERE thread_id = %s AND node_name = %s AND version < %s
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (thread_id, ctx.node_name, ctx.version),
                )
                _prev_row = await _cur.fetchone()
            if _prev_row:
                await copy_skills_from_node(str(_prev_row["node_id"]), node_id, thread_id)

    # --------------------------------------------------------------------- #
    # Build all LangChain StructuredTools and their ToolInfo metadata
    # --------------------------------------------------------------------- #
    collected: dict[str, Any] = {}
    all_lc_tools = [t.as_tool(node, ctx, collected) for t in node.tasks]
    all_tool_infos = get_tool_infos_for_tasks(node.tasks)

    # --------------------------------------------------------------------- #
    # Progressive context assembly
    # 1. Auto-compact memory (keeps context tight).
    # 2. Fetch all active skills and memory.
    # 3. Extract task keywords, pre-filter candidates, then let the LLM
    #    select which tools / skills / memory entries to load via structured
    #    JSON response.  Falls back to all tools on any selection failure.
    # --------------------------------------------------------------------- #
    await compact_if_needed(node_id, thread_id)
    all_skills = await get_skills(node_id, active_only=True)
    all_memory = await get_memory_entries(node_id)

    cap_ctx = await resolve_capabilities(user_message, all_tool_infos, all_skills, all_memory)

    # Narrow LangChain StructuredTools to the LLM-selected subset.
    selected_tool_names = {t.name for t in cap_ctx.tools}
    tools = [t for t in all_lc_tools if t.name in selected_tool_names]

    full_system = _build_system_context(system_prompt, tools, cap_ctx.skills, cap_ctx.memory)

    # --------------------------------------------------------------------- #
    # Check pause flag before invoking the agent
    # --------------------------------------------------------------------- #
    if await is_agent_pause_flag_set(node_id):
        auto_resume = await is_agent_auto_resume_set(node_id)
        raise AgentPausedError(node_id, auto_resume=auto_resume)

    # --------------------------------------------------------------------- #
    # Persist the initial user message to agent memory
    # --------------------------------------------------------------------- #
    seq_num = await get_max_seq_num(node_id)
    seq_num += 1
    await append_memory_entry(
        thread_id=thread_id,
        node_id=node_id,
        entry_type="reasoning",
        content={"text": user_message},
        seq_num=seq_num,
    )

    # --------------------------------------------------------------------- #
    # ReAct loop: bind tools → invoke → dispatch tool calls → repeat
    #
    # Tool-call guidance strategy (mirrors Claude Code's clarification loop):
    # • The system prompt's Tier-2 tool catalogue already says "always call
    #   the appropriate tool".  That is the primary signal.
    # • If the model answers directly on step 0 despite having tools AND
    #   collected is still empty (no cached result from prior-run memory),
    #   inject a single HumanMessage nudge and retry.  This is more reliable
    #   than tool_choice="required" which Ollama/Qwen3 can silently ignore.
    # • On subsequent runs that have fresh task_result memory, the model may
    #   legitimately skip re-calling the tool — that is the "gradually piling
    #   up memory" progressive behaviour the user requested.
    # --------------------------------------------------------------------- #
    llm = get_llm(provider="ollama")
    bound_llm = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}
    tool_names = ", ".join(t.name for t in tools) if tools else ""

    messages: list = [
        SystemMessage(content=full_system),
        HumanMessage(content=user_message),
    ]

    response_text = ""
    nudge_sent = False
    for _step in range(max_iterations):
        response = await bound_llm.ainvoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            if tools and not collected and not nudge_sent:
                # Model answered directly despite having tools and no cached
                # memory results yet.  Inject one clarification nudge and
                # retry — mirrors Claude Code's clarification-loop pattern.
                messages.append(HumanMessage(
                    content=(
                        f"You must call one of the available tools to complete "
                        f"this task. Do not answer from your own knowledge. "
                        f"Call {tool_names} now."
                    )
                ))
                nudge_sent = True
                continue
            if nudge_sent and not collected:
                logger.error(
                    "agent loop: model skipped tool calls even after nudge "
                    "(node_id=%s) — collected empty, build_output may fail",
                    node_id,
                )
            response_text = getattr(response, "content", "") or ""
            break

        for tc in tool_calls:
            tool = tool_map.get(tc["name"])
            if tool is None:
                logger.error("agent called unknown tool %r — skipping", tc["name"])
                continue
            tool_result = await tool.ainvoke(tc["args"])
            messages.append(
                ToolMessage(content=str(tool_result), tool_call_id=tc["id"])
            )
            # Persist the invocation and its result so future runs have
            # structured task_result context (highest-value memory type).
            seq_num += 1
            await append_memory_entry(
                thread_id=thread_id,
                node_id=node_id,
                entry_type="tool_call",
                content={"tool_name": tc["name"], "args": tc["args"]},
                seq_num=seq_num,
            )
            seq_num += 1
            # For streaming tasks that capture chain-of-thought, store as
            # {answer_json: thinking_text} so the agent can later reason over
            # both the structured result and how it was derived.
            task_output = collected.get(tc["name"])
            thinking_text = task_output.thinking if task_output is not None else None
            if thinking_text:
                task_result_content: dict = {
                    _json.dumps(tool_result, default=str): thinking_text
                }
            else:
                task_result_content = {
                    "tool_name": tc["name"],
                    "result": _json.dumps(tool_result, default=str),
                }
            await append_memory_entry(
                thread_id=thread_id,
                node_id=node_id,
                entry_type="task_result",
                content=task_result_content,
                seq_num=seq_num,
            )

    # --------------------------------------------------------------------- #
    # Persist the final agent response to agent memory
    # --------------------------------------------------------------------- #
    if response_text:
        seq_num += 1
        await append_memory_entry(
            thread_id=thread_id,
            node_id=node_id,
            entry_type="reasoning",
            content={"text": response_text[:500]},
            seq_num=seq_num,
        )

    # --------------------------------------------------------------------- #
    # Memory-restore fallback
    #
    # When the model refuses to call tools even after a nudge (typically
    # because prior task_result memory entries made it believe the work is
    # already done), attempt to reconstruct TaskOutput values from the most
    # recent task_result memory entry per tool.  This preserves the
    # progressive-memory design while preventing a hard AP-002 failure.
    # --------------------------------------------------------------------- #
    if nudge_sent and not collected:
        import ast

        from backend.langgraph.models.models import TaskContext, TaskOutput

        task_map = {t.name: t for t in node.tasks}
        # Walk memory newest-first; take only the first (most-recent) result
        # per tool name so stale duplicates don't shadow newer entries.
        seen_tools: set[str] = set()
        for entry in sorted(all_memory, key=lambda e: -e.seq_num):
            if entry.entry_type != "task_result":
                continue
            content = entry.content
            # New format: {answer_json_str: thinking_text} — single-key dict
            # where the key is the serialised answer JSON.
            if len(content) == 1 and "tool_name" not in content:
                answer_key = next(iter(content))
                result_raw = answer_key
                # tool_name is not stored in this format; match by trying each
                # registered task until one validates successfully.
                for tool_name_candidate, task_def in task_map.items():
                    if tool_name_candidate in seen_tools:
                        continue
                    try:
                        content_dict = _json.loads(result_raw)
                        content_obj = task_def.output_type.model_validate(content_dict)
                    except Exception:
                        continue
                    seen_tools.add(tool_name_candidate)
                    fake_ctx = TaskContext(
                        thread_id=thread_id,
                        node_id=node_id,
                        node_name=node.node_name,
                        task_id="memory-restored",
                        task_name=tool_name_candidate,
                    )
                    collected[tool_name_candidate] = TaskOutput(
                        ctx=fake_ctx,
                        content=content_obj,
                        thinking=content.get(answer_key),
                    )
                    logger.error(
                        "agent loop: restored %r result from prior memory — "
                        "model refused to re-call tool (node_id=%s)",
                        tool_name_candidate, node_id,
                    )
                    break
                continue
            # Legacy format: {"tool_name": ..., "result": ...}
            tool_name = content.get("tool_name")
            result_raw = content.get("result")
            if not tool_name or not result_raw or tool_name in seen_tools:
                continue
            seen_tools.add(tool_name)
            if tool_name not in task_map:
                continue
            task_def = task_map[tool_name]
            try:
                try:
                    content_dict = _json.loads(result_raw)
                except (ValueError, TypeError):
                    content_dict = ast.literal_eval(result_raw)
                content_obj = task_def.output_type.model_validate(content_dict)
                fake_ctx = TaskContext(
                    thread_id=thread_id,
                    node_id=node_id,
                    node_name=node.node_name,
                    task_id="memory-restored",
                    task_name=tool_name,
                )
                collected[tool_name] = TaskOutput(ctx=fake_ctx, content=content_obj)
                logger.error(
                    "agent loop: restored %r result from prior memory — "
                    "model refused to re-call tool (node_id=%s)",
                    tool_name, node_id,
                )
            except Exception as restore_err:
                logger.error(
                    "agent loop: could not restore %r from memory: %s (node_id=%s)",
                    tool_name, restore_err, node_id,
                )

    return collected


__all__ = ["run_agent_loop"]
