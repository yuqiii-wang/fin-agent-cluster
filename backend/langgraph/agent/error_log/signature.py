"""Message cleaning and signature normalization for per-thread log capture.

Two transforms keep the stored set small and free of duplicate / stack-trace
noise:

* :func:`clean_message` reduces a raw log record to a single line plus, when an
  exception is attached, only the exception *type and message* (never the full
  traceback) -- so long stack traces never reach the store.
* :func:`make_signature` normalizes a cleaned message into a dedup key by
  collapsing whitespace and replacing run-specific numbers (iteration counts,
  hex ids, timestamps) with a placeholder, so near-identical records collapse
  into a single counted entry.
"""

from __future__ import annotations

import logging
import re

# Run-specific tokens that must not break deduplication: any alphanumeric token
# containing at least one digit (counters like ``iter=3``, hex ids, UUID blobs,
# timestamps) collapses to a single placeholder.
_DIGIT_TOKEN_RE = re.compile(r"\b\w*\d\w*\b")
_WS_RE = re.compile(r"\s+")

# Signature length cap -- enough to distinguish distinct messages cheaply.
_SIGNATURE_LEN = 200


def clean_message(record: logging.LogRecord, *, char_cap: int) -> str:
    """Return a single-line, traceback-free message for *record*.

    Keeps only the first line of the formatted message and, when the record
    carries exception info, appends the exception type and first line of its
    string form -- deliberately omitting the multi-line traceback so the store
    never accumulates long stack traces.

    Args:
        record:   The log record being captured.
        char_cap: Maximum number of characters to retain.

    Returns:
        Cleaned message truncated to *char_cap* characters.
    """
    text = record.getMessage().split("\n", 1)[0].strip()

    exc_info = record.exc_info
    if exc_info and exc_info[1] is not None:
        exc = exc_info[1]
        exc_first_line = str(exc).split("\n", 1)[0].strip()
        text = f"{text} | {type(exc).__name__}: {exc_first_line}".strip(" |")

    return text[:char_cap]


def make_signature(logger_name: str, level: str, message: str) -> str:
    """Return a dedup key for a cleaned *message*.

    Collapses whitespace and replaces every alphanumeric token containing a
    digit with ``#`` so records that differ only by run-specific values (e.g.
    ``iter=3`` vs ``iter=7``, hex ids, UUIDs) map to the same signature.

    Args:
        logger_name: Logger that emitted the record.
        level:       Log level name.
        message:     Cleaned message from :func:`clean_message`.

    Returns:
        A compact, stable signature string.
    """
    normalized = _DIGIT_TOKEN_RE.sub("#", message)
    normalized = _WS_RE.sub(" ", normalized).strip()
    return f"{logger_name}|{level}|{normalized[:_SIGNATURE_LEN]}"


__all__ = ["clean_message", "make_signature"]
