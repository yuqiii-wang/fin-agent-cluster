"""Agent capability orchestration: progressive loading with LLM-based selection.

This module is the orchestration layer.  Domain-specific logic lives in the
sub-modules it delegates to:

- ``tools``   — ToolInfo model and NodeTask→ToolInfo bridge.
- ``skills``  — skill storage, retrieval, and keyword candidate search.
- ``memory``  — memory storage, retrieval, and keyword candidate search.

Flow
----
1. Fetch all active skills and memory entries for the node.
2. Extract keywords from the task description.
3. Pre-filter skill/memory candidates by keyword search (in sub-modules).
4. Ask the LLM (structured JSON) to select relevant tools, skills, and memory.
5. Return a CapabilityContext with only the selected, fully-loaded items.

Backward-compatibility
----------------------
``AgentCapabilities`` and ``get_agent_capabilities`` are retained for the API
layer (``/api/v1/threads/{thread_id}/nodes/{node_id}/agent/capabilities``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pydantic import BaseModel, Field

from backend.langgraph.agent.memory.models import MemoryEntry
from backend.langgraph.agent.memory.ops import extract_memory_text, get_memory_entries, search_memory_candidates
from backend.langgraph.agent.skills.models import Skill
from backend.langgraph.agent.skills.ops import get_skills, search_skill_candidates
from backend.langgraph.agent.tools.models import ToolInfo
from backend.langgraph.agent.tools.ops import get_tools_for_node

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits / tuning constants
# ---------------------------------------------------------------------------

# Maximum candidates shown to the LLM during the selection step.
_MAX_SKILL_CANDIDATES = 10
_MAX_MEMORY_CANDIDATES = 15

# Minimum keyword length to avoid noise words.
_MIN_KEYWORD_LEN = 4

# Common stopwords excluded from keyword extraction.
_STOPWORDS = frozenset({
    "this", "that", "with", "from", "have", "will", "been", "they", "were",
    "their", "also", "when", "what", "which", "about", "into", "more", "some",
    "then", "than", "each", "only", "both", "very", "just", "your", "like",
    "need", "should", "would", "could", "using", "based", "data", "show",
    "list", "give", "find", "look", "call", "return", "make", "take",
    "please", "stock", "company", "analyze", "provide", "identify",
})


# ===========================================================================
# Orchestration-layer data models
# ===========================================================================


class AgentCapabilities(BaseModel):
    """Full capability snapshot for an agent node execution (API view).

    Attributes:
        tools:  Fixed NodeTask tools registered on the node class.
        skills: User-defined skill instructions (active only).
        memory: Chronological memory entries captured during execution.
    """

    tools: list[ToolInfo]
    skills: list[Skill]
    memory: list[MemoryEntry]


class CapabilitySelection(BaseModel):
    """LLM-selected capability subset returned as structured JSON.

    Attributes:
        tools:  Tool names (from available tool list) to bind for this run.
        skills: Skill IDs whose instructions should be injected in context.
        memory: Memory entry IDs relevant for context.
    """

    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)


class CapabilityContext(BaseModel):
    """Fully resolved capabilities after progressive selection.

    Attributes:
        tools:  Selected ToolInfo objects (used to filter bound LangChain tools).
        skills: Selected Skill objects (instructions injected in system prompt).
        memory: Selected MemoryEntry objects (context injected in system prompt).
    """

    tools: list[ToolInfo]
    skills: list[Skill]
    memory: list[MemoryEntry]


# ===========================================================================
# Keyword extraction (orchestrator-level helper)
# ===========================================================================


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from *text* for candidate pre-filtering.

    Tokenises, lowercases, deduplicates, and strips stopwords and very short
    words.  The resulting list is used to score skills and memory entries
    before passing candidates to the LLM.

    Args:
        text: Free-form task description or user message.

    Returns:
        Ordered list of distinct keywords (≥ ``_MIN_KEYWORD_LEN`` chars).
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text.lower())
    seen: set[str] = set()
    keywords: list[str] = []
    for w in words:
        if len(w) >= _MIN_KEYWORD_LEN and w not in _STOPWORDS and w not in seen:
            seen.add(w)
            keywords.append(w)
    return keywords


# ===========================================================================
# LLM-based selection (structured JSON)
# ===========================================================================


def _strip_thinking(text: str) -> str:
    """Remove ``<think>…</think>`` blocks emitted by reasoning models."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json_block(text: str) -> str:
    """Extract the outermost ``{…}`` JSON object from *text*."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


async def _llm_select_capabilities(
    tools: list[ToolInfo],
    skill_candidates: list[Skill],
    memory_candidates: list[MemoryEntry],
    task_desc: str,
) -> CapabilitySelection:
    """Invoke the LLM to select relevant capabilities for *task_desc*.

    Builds a structured selection prompt showing:
    - All available tools (name + description).
    - Pre-filtered skill candidates (id + summary).
    - Pre-filtered memory candidates (id + type + content snippet).

    The LLM must respond with a JSON object only (Ollama ``format: json``
    mode is used for clean output):

    .. code-block:: json

        {
          "tools":  ["tool_name1"],
          "skills": ["skill_id1"],
          "memory": ["memory_id1", "memory_id2"]
        }

    The response is validated against the known id/name sets; any unrecognised
    values are dropped.  On any failure (parse error, LLM timeout, etc.) falls
    back to selecting **all** tools and all presented candidates.

    Args:
        tools:             All available ToolInfo objects.
        skill_candidates:  Pre-filtered Skill candidates.
        memory_candidates: Pre-filtered MemoryEntry candidates.
        task_desc:         The agent task description (user message).

    Returns:
        :class:`CapabilitySelection` with validated ids/names.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.llm.factory import get_llm

    tool_names = [t.name for t in tools]
    skill_ids = [s.skill_id for s in skill_candidates]
    memory_ids = [e.memory_id for e in memory_candidates]

    # ------------------------------------------------------------------ #
    # Build the selection prompt
    # ------------------------------------------------------------------ #
    def _tool_line(t: ToolInfo) -> str:
        return f'  {{"name": "{t.name}", "description": "{t.description[:120]}"}}'

    def _skill_line(s: Skill) -> str:
        return f'  {{"id": "{s.skill_id}", "summary": "{s.summary[:100]}"}}'

    def _mem_line(e: MemoryEntry) -> str:
        snippet = extract_memory_text(e.content)[:120].replace('"', "'")
        return f'  {{"id": "{e.memory_id}", "type": "{e.entry_type}", "text": "{snippet}"}}'

    tool_block = "\n".join(_tool_line(t) for t in tools) or "  (none)"
    skill_block = "\n".join(_skill_line(s) for s in skill_candidates) or "  (none)"
    memory_block = "\n".join(_mem_line(e) for e in memory_candidates) or "  (none)"

    system_msg = (
        "You are a capability selector for an AI agent. "
        "Given a task and lists of available tools, skill instructions, and memory entries, "
        "select only the items that are directly relevant to completing the task.\n\n"
        'Respond with ONLY a valid JSON object — no markdown, no explanation — '
        'in exactly this format:\n'
        '{"tools": [...], "skills": [...], "memory": [...]}\n\n'
        "Rules:\n"
        '- "tools": array of tool names from the provided list that must be called\n'
        '- "skills": array of skill IDs whose instructions apply to this task\n'
        '- "memory": array of memory entry IDs that provide useful prior context\n'
        "- Include only names/IDs that appear in the lists below\n"
        "- Prefer relevance over completeness — omit items that do not help"
    )

    user_msg = (
        f"Task: {task_desc}\n\n"
        f"Available tools:\n{tool_block}\n\n"
        f"Skill candidates:\n{skill_block}\n\n"
        f"Memory candidates:\n{memory_block}\n\n"
        "Select relevant capabilities and return JSON."
    )

    # ------------------------------------------------------------------ #
    # Invoke LLM via non-streaming path with format=json for clean output
    # ------------------------------------------------------------------ #
    llm = get_llm(provider="ollama")
    messages = [SystemMessage(content=system_msg), HumanMessage(content=user_msg)]

    try:
        result = await asyncio.to_thread(
            lambda: llm._generate(messages, format="json")  # type: ignore[attr-defined]
        )
        raw = str(result.generations[0].message.content)
    except Exception as exc:
        logger.error(
            "capability selection LLM call failed: %s — using all tools and candidates", exc
        )
        return CapabilitySelection(tools=tool_names, skills=skill_ids, memory=memory_ids)

    # ------------------------------------------------------------------ #
    # Parse and validate JSON response
    # ------------------------------------------------------------------ #
    raw = _strip_thinking(raw)
    raw = _extract_json_block(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(
            "capability selection JSON parse failed: %s — raw=%r — using all candidates",
            exc, raw[:200],
        )
        return CapabilitySelection(tools=tool_names, skills=skill_ids, memory=memory_ids)

    valid_tools = [n for n in data.get("tools", []) if n in tool_names]
    valid_skills = [i for i in data.get("skills", []) if i in skill_ids]
    valid_memory = [i for i in data.get("memory", []) if i in memory_ids]

    # Always include at least all tools as fallback (agent must be able to act).
    return CapabilitySelection(
        tools=valid_tools or tool_names,
        skills=valid_skills,
        memory=valid_memory,
    )


# ===========================================================================
# Progressive capability resolution (main entry point for loop.py)
# ===========================================================================


async def resolve_capabilities(
    task_desc: str,
    all_tool_infos: list[ToolInfo],
    all_skills: list[Skill],
    all_memory: list[MemoryEntry],
) -> CapabilityContext:
    """Progressively resolve agent capabilities for a task.

    Steps
    -----
    1. Short-circuit when there are no skills or memory — return all tools
       immediately with no LLM selection call.
    2. Extract keywords from *task_desc*.
    3. Pre-filter skills and memory entries by keyword search, limiting
       candidate counts to ``_MAX_SKILL_CANDIDATES`` and
       ``_MAX_MEMORY_CANDIDATES``.
    4. Call the LLM to select relevant tools, skills, and memory from the
       candidates via structured JSON output.
    5. Resolve selected ids/names back to full model instances.

    Args:
        task_desc:      Free-form description of the current task (user message).
        all_tool_infos: All ToolInfo objects for the node.
        all_skills:     All active skills for the node.
        all_memory:     All active memory entries for the node.

    Returns:
        :class:`CapabilityContext` containing only the selected, fully-loaded
        capabilities.
    """
    # Fast path: nothing to select from — include all tools.
    if not all_skills and not all_memory:
        return CapabilityContext(tools=all_tool_infos, skills=[], memory=[])

    keywords = _extract_keywords(task_desc)
    skill_candidates = search_skill_candidates(all_skills, keywords, _MAX_SKILL_CANDIDATES)
    memory_candidates = search_memory_candidates(all_memory, keywords, _MAX_MEMORY_CANDIDATES)

    selection = await _llm_select_capabilities(
        all_tool_infos, skill_candidates, memory_candidates, task_desc
    )

    # Resolve back to full objects.
    skill_map = {s.skill_id: s for s in all_skills}
    memory_map = {e.memory_id: e for e in all_memory}
    selected_tool_names = set(selection.tools)

    return CapabilityContext(
        tools=[t for t in all_tool_infos if t.name in selected_tool_names],
        skills=[skill_map[sid] for sid in selection.skills if sid in skill_map],
        memory=[memory_map[mid] for mid in selection.memory if mid in memory_map],
    )


# ===========================================================================
# API-layer helper (backward-compatible)
# ===========================================================================


async def get_agent_capabilities(node_id: str, *, include_all_memory: bool = False) -> AgentCapabilities:
    """Return the full (unfiltered) capability snapshot for *node_id*.

    Used by the API layer to display all capabilities to the UI.  The
    agent loop uses :func:`resolve_capabilities` for selective loading.

    Args:
        node_id:           Agent node UUID.
        include_all_memory: When ``True`` (terminal nodes), return all memory
                            entries regardless of status so the UI can display
                            the complete history in read-only mode.

    Returns:
        :class:`AgentCapabilities` with all three capability lists populated.
    """
    tools_task = asyncio.create_task(get_tools_for_node(node_id))
    skills_task = asyncio.create_task(get_skills(node_id, active_only=True))
    memory_task = asyncio.create_task(
        get_memory_entries(
            node_id,
            include_forgotten=include_all_memory,
            include_compacted=include_all_memory,
        )
    )

    tools, skills, memory = await asyncio.gather(tools_task, skills_task, memory_task)

    return AgentCapabilities(tools=tools, skills=skills, memory=memory)


__all__ = [
    "AgentCapabilities",
    "CapabilityContext",
    "CapabilitySelection",
    "get_agent_capabilities",
    "resolve_capabilities",
]
