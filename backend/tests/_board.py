"""Test helper: make an agent a project member so dispatch can reach the board."""

from __future__ import annotations

import backend.db as db_mod
from backend.models import ProjectMember


def join_project(project_id: str, agent_id: str) -> None:
    """Agent and its backing profile share an id (1:1)."""
    with db_mod.SessionLocal() as db:
        db.add(ProjectMember(project_id=project_id, profile_id=agent_id))
        db.commit()
