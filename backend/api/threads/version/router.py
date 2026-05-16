"""backend.api.threads.version — version graph API endpoint.

Routes (all mounted on the parent ``/threads`` router):

    GET  /api/v1/threads/{thread_id}/version/{version_id}
        — return the fork node and all branch nodes for a given version.

Response structure (:class:`~backend.users.schemas.VersionGraphResponse`):
    - ``version``:        The requested fork generation.
    - ``thread_id``:      The owning thread.
    - ``fork_node``:      The ``is_forked=TRUE`` node that began this branch
                          (``None`` for version 0 / original run).
    - ``source_version``: The version that was forked from
                          (``None`` for version 0).
    - ``nodes``:          All nodes that executed in this version.

The ``fork_node.prev_node_ids`` point to nodes from the source version so
the UI can connect the new branch to its divergence point.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from backend.users.queries import get_version_graph
from backend.users.schemas import VersionGraphResponse

router = APIRouter()

TThreadId = Annotated[str, Path(description="LangGraph thread UUID")]
TVersionId = Annotated[int, Path(description="Fork generation number (0 = original run)", ge=0)]


@router.get(
    "/{thread_id}/version/{version_id}",
    response_model=VersionGraphResponse,
    tags=["version"],
)
async def get_version_graph_route(
    thread_id: TThreadId,
    version_id: TVersionId,
) -> VersionGraphResponse:
    """Return the fork node and all branch nodes for a given version.

    Version 0 is the original run (no fork node).  Version 1+ are re-explore
    branches; each has exactly one ``is_forked=TRUE`` node whose
    ``forked_from_version`` identifies the source branch.

    Use ``fork_node.prev_node_ids`` to connect this version's entry point to
    the shared nodes from the source version when rendering a version graph.
    """
    return await get_version_graph(thread_id, version_id)
