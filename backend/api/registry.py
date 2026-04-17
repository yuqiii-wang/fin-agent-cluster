"""Shared in-process registry of active LangGraph background tasks.

Centralises the ``running_tasks`` dict so the query router (writer) and the
stream router (reader) can both access it without a circular import.
"""

from __future__ import annotations

import asyncio

# Maps thread_id → asyncio.Task running _run_graph.
# Entries are added when a query starts and removed when it finishes/fails.
# If the server restarts mid-query this dict is empty while the DB may still
# show status='running' — callers should treat that as an orphaned query.
running_tasks: dict[str, asyncio.Task] = {}
