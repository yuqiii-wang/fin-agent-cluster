"""Tasks for conclusion_node.

Note: stream_conclusion uses the streaming Celery worker; its handler is
not registered in the completion HANDLERS dict.  The HANDLERS slice here
is intentionally empty — it is included for structural consistency and to
keep the assembly pattern in nodes/__init__.py uniform.
"""

from backend.langgraph.nodes.mock_conclusion_node.tasks.stream_conclusion import stream_conclusion

# Streaming tasks run via delegate_stream, not the completion HANDLERS registry.
HANDLERS: dict = {}

__all__ = ["stream_conclusion", "HANDLERS"]
