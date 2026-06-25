"""Default "professionalization" backlog — template load + project seeding.

The product ships a default backlog (logging, unit tests, integration tests via
Bruno, a manual test guide, security checks, CI/CD) that a new project can seed
and run with the Conductor. The backlog is stored as a template YAML
(templates/default_tasks/professionalization.yaml), never hardcoded — this
module just parses it and materializes it into a project's epics + tasks.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "default_tasks"
DEFAULT_TASKS_PATH = _TEMPLATES_DIR / "professionalization.yaml"


class DefaultTask(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    dod: list[str] = Field(default_factory=list)


class DefaultEpic(BaseModel):
    title: str
    description: str = ""
    color: str = "#7c4dff"
    tasks: list[DefaultTask] = Field(default_factory=list)


class DefaultTasksTemplate(BaseModel):
    name: str
    description: str = ""
    epics: list[DefaultEpic] = Field(default_factory=list)


def load_default_tasks(path: str | Path | None = None) -> DefaultTasksTemplate:
    """Parse a default-tasks template YAML into a validated model."""
    p = Path(path) if path else DEFAULT_TASKS_PATH
    if not p.exists():
        raise FileNotFoundError(f"Default tasks template not found: {p}")
    data = yaml.safe_load(p.read_text())
    if not isinstance(data, dict):
        raise ValueError("Default tasks YAML must be a mapping at the top level")
    return DefaultTasksTemplate(**data)


def seed_default_tasks(
    project_id: str,
    *,
    template: DefaultTasksTemplate | None = None,
    status: str = "backlog",
    actor: str = "system",
) -> dict:
    """Materialize the default backlog into a project's epics + tasks.

    Idempotent on epic title: an epic already present in the project is reused
    and its tasks are skipped, so re-seeding never duplicates the backlog.

    Returns: {"epics_created": int, "tasks_created": int, "skipped": [title...]}
    """
    from backend import services as core_services

    tmpl = template or load_default_tasks()
    existing = {e["title"] for e in core_services.list_epics(project_id, actor=actor)}

    epics_created = 0
    tasks_created = 0
    skipped: list[str] = []
    for epic in tmpl.epics:
        if epic.title in existing:
            skipped.append(epic.title)
            continue
        epic_row = core_services.create_epic(
            project_id, title=epic.title, description=epic.description,
            color=epic.color, actor=actor,
        )
        epics_created += 1
        for task in epic.tasks:
            core_services.create_task(
                project_id=project_id,
                title=task.title,
                description=task.description,
                status=status,
                priority=task.priority,
                dod_items=[{"text": d, "checked": False} for d in task.dod],
                epic_id=epic_row["id"],
                actor=actor,
            )
            tasks_created += 1

    return {"epics_created": epics_created, "tasks_created": tasks_created,
            "skipped": skipped}
