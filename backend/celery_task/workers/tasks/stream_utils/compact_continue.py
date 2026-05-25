"""Compact-and-continue helpers for streaming Celery tasks.

When an LLM reasoning stream enters a repetition loop, the prior thinking is
compressed and re-submitted so the model can continue from where it stopped.
"""

from __future__ import annotations

import json
from typing import Any


def detect_and_compress_repetition(thinking: str) -> tuple[str, str, int]:
    """Detect consecutive line repetition at the end of *thinking* and compress it.

    Splits *thinking* by newline and searches for the largest suffix where a
    fixed-length block of lines repeats at least twice consecutively.  Returns
    the non-repeating prefix, the repeating block text, and the repetition count.

    If no repetition is found ``repeat_count`` is 0 and ``repeating_block`` is
    an empty string.

    Args:
        thinking: Raw thinking text from a prior LLM streaming run.

    Returns:
        Tuple ``(non_repeating_prefix, repeating_block, repeat_count)`` where
        ``repeat_count >= 2`` means repetition was detected.
    """
    lines = thinking.split("\n")
    n = len(lines)
    if n < 2:
        return thinking, "", 0

    best_count = 1
    best_block_size = 0
    best_start = n

    # Try every block size from 1 up to half the total lines.
    for block_size in range(1, n // 2 + 1):
        block = lines[n - block_size:]
        count = 1
        pos = n - block_size
        while pos >= block_size and lines[pos - block_size:pos] == block:
            count += 1
            pos -= block_size
        if count >= 2 and count > best_count:
            best_count = count
            best_block_size = block_size
            best_start = pos

    if best_count < 2:
        return thinking, "", 0

    non_repeating = "\n".join(lines[:best_start])
    repeating_block = "\n".join(lines[best_start:best_start + best_block_size])
    return non_repeating, repeating_block, best_count


async def run_stream_compact_continue_async(
    thread_id: str,
    task_id: str,
    task_name: str,
    node_name: str,
    payload: dict[str, Any],
    prior_thinking_full: str,
    prior_thinking_compressed: str,
) -> dict[str, Any]:
    """Run a compact-and-continue retry stream.

    Builds the original prompt from *payload*, appends the compressed prior
    thinking as context, streams from the LLM, then stores the concatenation
    of *prior_thinking_full* and the new thinking as the final thinking in
    ``fin_agents.llm_responses``.

    Args:
        thread_id:               LangGraph thread UUID.
        task_id:                 Governance UUID of the task row.
        task_name:               UI-facing task label.
        node_name:               Owning node name.
        payload:                 Original serialised task input.
        prior_thinking_full:     Complete prior thinking text (for final DB storage).
        prior_thinking_compressed: Compressed prior thinking with repetitions folded.

    Returns:
        ``{"thinking": str | None, "answer": dict, "total_tokens": int, "latency_ms": int}``
        where ``thinking`` is the concatenation of prior and new thinking.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from backend.db.postgres.connection import raw_conn
    from .llm_selection import select_llm
    from .prompt_registry import get_stream_prompt_builders
    from .stream_core import run_stream_core

    builders = get_stream_prompt_builders()
    if task_name in builders:
        base_messages = builders[task_name](payload)
    else:
        # stream_llm path — rebuild the original messages.
        query = payload.get("query", "")
        stats_analysis = payload.get("stats_analysis", "")
        stats_key_metrics = payload.get("stats_key_metrics", {})
        news_sentiment = payload.get("news_sentiment", "")
        news_highlights: list[str] = payload.get("news_highlights", [])
        highlights_text = "\n".join(f"- {h}" for h in news_highlights) if news_highlights else "No highlights."
        metrics_text = json.dumps(stats_key_metrics, indent=2) if stats_key_metrics else "N/A"
        system_content = (
            "You are a quantitative financial analyst. Produce structured investment conclusions "
            "based on market research. Respond ONLY with a JSON object (no markdown fences, no extra "
            "text) with exactly these fields:\n"
            '{"summary": "<2-3 sentence overall conclusion>", '
            '"recommendation": "<Buy|Sell|Hold>", '
            '"confidence": "<High|Medium|Low>", '
            '"key_points": ["<point1>", "<point2>", ...], '
            '"risk_factors": ["<risk1>", "<risk2>", ...]}'
        )
        human_content = (
            f"Query: {query}\n\n"
            f"Statistical Analysis:\n{stats_analysis or 'Not available.'}\n\n"
            f"Key Metrics:\n{metrics_text}\n\n"
            f"News Sentiment:\n{news_sentiment or 'Not available.'}\n\n"
            f"News Highlights:\n{highlights_text}"
        )
        base_messages = [SystemMessage(content=system_content), HumanMessage(content=human_content)]

    # Append the compressed prior thinking as continuation context.
    continuation_note = (
        "The previous reasoning attempt stopped with repeated content. "
        "Here is the prior thinking (with repetitions compressed):\n\n"
        f"{prior_thinking_compressed}\n\n"
        "Please continue reasoning from this point without repeating yourself."
    )
    messages = base_messages + [HumanMessage(content=continuation_note)]

    llm = select_llm(payload.get("query", ""))
    new_result = await run_stream_core(
        thread_id, task_id, task_name, node_name, payload, messages, llm,
    )

    # Concatenate prior full thinking with the new thinking so the DB row
    # captures the complete reasoning chain across both streaming attempts.
    new_thinking: str | None = new_result.get("thinking")
    if prior_thinking_full and new_thinking:
        combined_thinking = prior_thinking_full + "\n<continuation>\n" + new_thinking
    elif prior_thinking_full:
        combined_thinking = prior_thinking_full
    else:
        combined_thinking = new_thinking

    # Overwrite the just-inserted llm_responses.thinking with the combined value
    # so the stored record reflects the full reasoning chain.
    if combined_thinking != new_thinking:
        async with raw_conn() as conn:
            await conn.execute(
                """
                UPDATE fin_agents.llm_responses
                SET thinking = %s
                WHERE id = (
                    SELECT id FROM fin_agents.llm_responses
                    WHERE task_id = %s
                    ORDER BY ts DESC
                    LIMIT 1
                )
                """,
                (combined_thinking, task_id),
            )

    return {**new_result, "thinking": combined_thinking}
