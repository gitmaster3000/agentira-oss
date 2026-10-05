"""Can an agent reach a project's board (the Agentira MCP / API)?

A run needs a profile with an API key (that is what authenticates the Agentira
MCP) and membership of the task's project. Without either the agent cannot read
the task, comment or finish_run, so dispatch refuses up front in plain words.
"""

from __future__ import annotations

from backend.forge.repos import project_members


def board_access_problem(db, agent, project_id: str | None) -> str | None:
    """Plain-language reason `agent` cannot reach the board, or None if it can.

    `project_id` None skips the membership check (identity is still checked)."""
    profile = agent.profile
    if profile is None or not (profile.api_key or "").strip():
        return (f"{agent.name} cannot reach this project board — it has no "
                "Agentira identity. Give it a profile with an API key.")
    if project_id and not project_members.is_member(
            db, project_id=project_id, profile_id=profile.id):
        return (f"{agent.name} cannot reach this project board — add it as a "
                "member of the project.")
    return None


def board_access_summary(db, agent) -> dict:
    """Agent-card view: checks identity and the agent's default project."""
    problem = board_access_problem(db, agent, agent.default_project_id)
    return {"ok": problem is None, "problems": [problem] if problem else []}
