"""Graph runner error code registry.

Error code prefixes
-------------------
``GRAPH_NOT_``   — Graph initialisation / lifecycle errors.
``GRAPH_DB_``    — Database connectivity errors blocking graph startup.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

# ── Graph initialisation ──────────────────────────────────────────────────────

#: Compiled graph singleton was accessed before init_compiled_graph() completed.
GRAPH_NOT_INITIALIZED = "GRAPH_NOT_INITIALIZED"

# ── Startup connectivity ──────────────────────────────────────────────────────

#: Database connection check failed during FastAPI lifespan startup.
GRAPH_DB_UNAVAILABLE = "GRAPH_DB_UNAVAILABLE"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each error code to a human-readable description.
GRAPH_RUNNER_ERRORS: dict[str, str] = {
    GRAPH_NOT_INITIALIZED: (
        "The compiled graph has not been initialised. "
        "Ensure init_compiled_graph() is called in the FastAPI lifespan before "
        "accepting requests."
    ),
    GRAPH_DB_UNAVAILABLE: (
        "Database connectivity check failed at startup. "
        "Verify PostgreSQL is reachable and credentials are correct."
    ),
}
