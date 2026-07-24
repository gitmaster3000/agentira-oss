"""Static tripwire for actorless calls into project-owned service APIs.

Ruff catches ordinary Python defects; this AST check is the project-specific
security lint that Ruff cannot express as a built-in rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


PROJECT_SCOPED_SERVICE_CALLS = {
    "delete_epic",
    "delete_project",
    "delete_task",
    "get_activity",
    "get_active_runs",
    "get_attachment",
    "get_attachment_bytes",
    "get_epic",
    "get_project",
    "get_project_activity",
    "get_run",
    "get_run_events",
    "get_task",
    "list_attachments",
    "list_epic_tasks",
    "list_project_attachments",
    "list_project_members",
    "list_project_repos",
    "list_runs",
    "list_runs_for_task",
    "remove_project_member",
    "update_project",
}


@pytest.mark.parametrize(
    "module_name",
    ["mcp_server.py", "rest_api.py", "forge/router.py"],
)
def test_project_scoped_service_calls_forward_authenticated_actor(module_name):
    path = Path(__file__).parents[1] / module_name
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "services"
            and func.attr in PROJECT_SCOPED_SERVICE_CALLS
        ):
            continue
        if not any(keyword.arg == "actor" for keyword in node.keywords):
            violations.append(f"{module_name}:{node.lineno} services.{func.attr}")

    assert violations == [], "actorless project service calls:\n" + "\n".join(
        violations,
    )
