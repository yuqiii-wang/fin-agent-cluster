"""Text parsing utilities for LLM streamed output."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_thinking_answer(text: str) -> tuple[str | None, str]:
    """Split a reasoning block from the rest of the streamed response.

    Handles two tag variants produced by different LLM providers:

    * ``<think>...</think>`` -- Ollama reasoning models (e.g. Qwen3) after
      normalisation by :meth:`OllamaLLM._astream`.
    * ``<thinking>...</thinking>`` -- Anthropic-style extended thinking or
      models that emit the tag verbatim.

    If the close tag is missing (stream was truncated), the remaining text
    is treated as thinking and the answer is returned as an empty string so
    callers can detect the incomplete state.

    If no reasoning block is present (normal for non-reasoning models and
    MockLLM) the full text is returned as the answer with ``thinking=None``.

    Args:
        text: Raw accumulated LLM output.

    Returns:
        A two-tuple ``(thinking, answer)`` where *thinking* is the content
        inside the reasoning tag (or ``None`` when absent) and *answer* is
        the remaining text after the close tag.
    """
    stripped = text.strip()
    for open_tag, close_tag in (("<think>", "</think>"), ("<thinking>", "</thinking>")):
        if open_tag not in stripped:
            continue
        _before, _, after_open = stripped.partition(open_tag)
        if close_tag in after_open:
            thinking_raw, _, answer = after_open.partition(close_tag)
            return thinking_raw.strip() or None, answer.strip()
        # Close tag missing -- stream was truncated or model forgot to close it.
        logger.error(
            "[stream_task] %s opened but %s never closed in LLM output; "
            "treating remaining text as thinking. First 120: %r",
            open_tag, close_tag, after_open[:120],
        )
        return after_open.strip() or None, ""
    # No reasoning block -- normal for non-reasoning models (MockLLM, plain Ollama).
    return None, stripped


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Extract a JSON object from text that may contain markdown fences or prose.

    Handles LLM responses that wrap the JSON in ````json ... ```` fences or
    prefix it with explanation text.  Falls back to ``{"raw": text}`` when no
    parseable JSON object is found, which allows callers to inspect the raw
    output for debugging.

    Args:
        text: Raw answer text after thinking has been stripped.

    Returns:
        Parsed JSON dict, or ``{"raw": text}`` on failure.
    """
    stripped = text.strip()

    # Strip common markdown code fences (```json ... ``` or ``` ... ```)
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner_lines = lines[1:]
        if inner_lines and inner_lines[-1].strip() == "```":
            inner_lines = inner_lines[:-1]
        stripped = "\n".join(inner_lines).strip()

    # Try direct parse first (fast path)
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Find the first balanced { ... } block in the text
    start = stripped.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(stripped[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break

    logger.error(
        "[stream_task] JSON extraction failed; storing raw text. First 120: %r",
        stripped[:120],
    )
    return {"raw": text}
