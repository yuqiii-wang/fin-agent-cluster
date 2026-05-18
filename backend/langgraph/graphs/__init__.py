"""backend.langgraph.graphs — graph definitions.

Two graphs are available:

* ``mock_graph``        — full multi-node mock graph (test mode).
* ``fin_trading_graph`` — production fin-trading graph.

Use :func:`backend.langgraph.compiled.init_compiled_graph` to compile the
appropriate graph at startup based on ``Settings.TEST_MODE``.
"""

from __future__ import annotations

__all__ = ["mock_graph", "fin_trading_graph"]
