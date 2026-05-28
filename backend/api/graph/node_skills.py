"""Node skills endpoint helpers — GET /api/v1/graph/node-skills.

Returns the list of markdown files from each node's ``skills/`` directory.
These files document the node's built-in workflow and capabilities.
"""

from __future__ import annotations

import pathlib
from typing import Optional

from pydantic import BaseModel

_NODES_DIR = pathlib.Path(__file__).parent.parent.parent / "langgraph" / "nodes"


class NodeSkillFile(BaseModel):
    """A single skill documentation file for a node."""

    filename: str
    content: str


class NodeSkillsResponse(BaseModel):
    """Skills files grouped by node name."""

    node_name: str
    skills: list[NodeSkillFile]


def get_all_node_skills() -> list[NodeSkillsResponse]:
    """Scan every node directory for ``skills/*.md`` files and return them.

    Returns:
        One :class:`NodeSkillsResponse` per node that has a non-empty
        ``skills/`` directory.  Nodes without a ``skills/`` directory or with
        no ``.md`` files are omitted.
    """
    result: list[NodeSkillsResponse] = []
    if not _NODES_DIR.is_dir():
        return result

    for node_dir in sorted(_NODES_DIR.iterdir()):
        if not node_dir.is_dir() or node_dir.name.startswith("_"):
            continue
        skills_dir = node_dir / "skills"
        if not skills_dir.is_dir():
            continue
        skill_files: list[NodeSkillFile] = []
        for md_file in sorted(skills_dir.glob("*.md")):
            try:
                skill_files.append(
                    NodeSkillFile(
                        filename=md_file.name,
                        content=md_file.read_text(encoding="utf-8"),
                    )
                )
            except OSError:
                continue
        if skill_files:
            result.append(
                NodeSkillsResponse(
                    node_name=node_dir.name,
                    skills=skill_files,
                )
            )
    return result


def get_node_skills(node_name: str) -> Optional[NodeSkillsResponse]:
    """Return the skills files for a single node by name.

    Args:
        node_name: The node directory name (e.g. ``"prepare_peers"``).

    Returns:
        :class:`NodeSkillsResponse` if the node has skill files, else ``None``.
    """
    node_dir = _NODES_DIR / node_name
    if not node_dir.is_dir():
        return None
    skills_dir = node_dir / "skills"
    if not skills_dir.is_dir():
        return None
    skill_files: list[NodeSkillFile] = []
    for md_file in sorted(skills_dir.glob("*.md")):
        try:
            skill_files.append(
                NodeSkillFile(
                    filename=md_file.name,
                    content=md_file.read_text(encoding="utf-8"),
                )
            )
        except OSError:
            continue
    if not skill_files:
        return None
    return NodeSkillsResponse(node_name=node_name, skills=skill_files)


__all__ = ["NodeSkillFile", "NodeSkillsResponse", "get_all_node_skills", "get_node_skills"]
