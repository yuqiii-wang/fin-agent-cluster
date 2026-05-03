from backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.models import QueryTaskOutput

class AddStaticQueryMetricsOutput(QueryTaskOutput):
    """Output for the add_static_query_metrics task.
    Inherits from QueryTaskOutput as it appends static data to it.
    """
    pass

__all__ = ["AddStaticQueryMetricsOutput"]