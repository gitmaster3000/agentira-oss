"""AP-3: Pure template parser — YAML → typed Template object.

No DB writes. Validates structure, returns a Pydantic model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, validator


class TemplateAgent(BaseModel):
    name: str
    role: str
    model: str
    system_prompt_file: str = ""
    allowed_tools: list[str] = Field(default_factory=list)


class ACCheckType(BaseModel):
    name: str
    description: str = ""
    runner: str
    pass_condition: str
    timeout_sec: int = 60


class ConductorConfig(BaseModel):
    auto_assign: bool = True
    pick_strategy: str = "highest_priority_unblocked"
    respect_dependencies: bool = True
    notify_on_block: bool = True
    digest_schedule: str = "daily"


class WorkflowRoleOverride(BaseModel):
    """Per-project workflow role override — mirrors the `roles:` section of
    templates/workflow/default.yaml (backend/forge/workflow.py:RoleSpec).
    Structural validation only; the workflow driver owns runtime resolution."""
    match: list[str] = Field(default_factory=list)
    exclude_previous_assignee: bool = False
    fallback: str = "none"          # "any" | "none"
    prompt: str = ""

    @validator("fallback")
    def fallback_known(cls, v):
        if v not in ("any", "none"):
            raise ValueError("fallback must be 'any' or 'none'")
        return v


_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"
_DEFAULT_TASKS_DIR = _TEMPLATES_ROOT / "default_tasks"


class Template(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str = ""
    trigger: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    agents: list[TemplateAgent] = Field(default_factory=list)
    ac_check_types: list[ACCheckType] = Field(default_factory=list)
    conductor: ConductorConfig = Field(default_factory=ConductorConfig)
    # Refs to task-backlog templates under templates/default_tasks/, parsed
    # by backend/default_tasks.py (e.g. "professionalization" or
    # "professionalization.yaml").
    default_tasks: list[str] = Field(default_factory=list)
    # Workflow pipeline columns (templates/workflow/*.yaml `columns:`), kept
    # in sync with the board `columns:` above — see SCHEMA.md.
    workflow_columns: list[str] = Field(default_factory=list)
    # Per-project workflow role overrides (see WorkflowRoleOverride).
    workflow_roles: dict[str, WorkflowRoleOverride] = Field(default_factory=dict)

    @validator("name")
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("template name cannot be empty")
        return v.strip()

    @validator("columns")
    def columns_not_empty(cls, v):
        if not v:
            raise ValueError("template must define at least one column")
        return v

    @validator("agents")
    def agents_not_empty(cls, v):
        if not v:
            raise ValueError("template must define at least one agent")
        return v

    @validator("default_tasks", each_item=True)
    def default_tasks_ref_exists(cls, v):
        ref = v if v.endswith(".yaml") else f"{v}.yaml"
        if not (_DEFAULT_TASKS_DIR / ref).exists():
            raise ValueError(
                f"default_tasks entry not found: templates/default_tasks/{ref}"
            )
        return v

    @validator("workflow_columns")
    def workflow_columns_match_columns(cls, v, values):
        if v:
            columns = values.get("columns") or []
            unknown = [c for c in v if c not in columns]
            if unknown:
                raise ValueError(
                    f"workflow_columns not present in columns: {unknown}"
                )
        return v


def load_template(path: str | Path) -> Template:
    """Parse a template YAML file and return a validated Template.

    Raises:
        FileNotFoundError: if path doesn't exist
        ValueError: if YAML is malformed or validation fails
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Template not found: {p}")

    raw = p.read_text()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Template YAML must be a mapping at the top level")

    return Template(**data)


# ── AP-4: instantiation ──────────────────────────────────────────────


def instantiate_project_from_template(
    template: Template,
    project_name: str,
    *,
    actor: str = "system",
) -> dict:
    """Materialize a Template into a Project + agent rows + AC registry.

    Idempotent: a second call with the same (template.name, project_name)
    returns the existing project and skips any agent already present
    (matched by name). Re-running is safe — useful for retries / replays.

    Returns:
        {
          "project": {...},                 # Project dict
          "created": bool,                  # False on idempotent return
          "agents_created": [name, ...],    # newly created agent names
          "agents_skipped": [name, ...],    # already-present agents
        }
    """
    import json
    from backend import services as core_services
    from backend.db import SessionLocal
    from backend.models import Project, Profile

    # 1. Idempotency: same template_name + project_name → return existing.
    with SessionLocal() as db:
        existing = (db.query(Project)
                      .filter(Project.template_name == template.name,
                              Project.name == project_name)
                      .first())
        if existing:
            proj_dict = core_services._project_to_dict(existing)
            return {"project": proj_dict, "created": False,
                    "agents_created": [], "agents_skipped": []}

    # 2. Create the project (descriptions inherited from the template).
    project = core_services.create_project(
        project_name, description=template.description, actor=actor,
    )

    # 3. Stamp template provenance + AC registry on the new row.
    with SessionLocal() as db:
        p = db.query(Project).filter(Project.id == project["id"]).first()
        if p:
            p.template_name = template.name
            if template.ac_check_types:
                p.ac_check_types_json = json.dumps(
                    [ct.model_dump() for ct in template.ac_check_types],
                )
            db.commit()
            db.refresh(p)
            project = core_services._project_to_dict(p)

    # 4. Create agent rows. Per-agent idempotent on `name` — re-running
    # against a project that already has some agents (because an earlier
    # run partially succeeded) won't duplicate them. Created as service
    # accounts; the template doesn't pin a runtime (host-specific
    # concern), so runtime_id stays null until the operator binds one.
    created: list[str] = []
    skipped: list[str] = []
    for ta in template.agents:
        with SessionLocal() as db:
            existing_prof = (db.query(Profile)
                               .filter(Profile.name == ta.name)
                               .first())
        if existing_prof:
            skipped.append(ta.name)
            continue
        try:
            core_services.create_service_account(ta.name)
            created.append(ta.name)
        except Exception:
            skipped.append(ta.name)

    return {"project": project, "created": True,
            "agents_created": created, "agents_skipped": skipped}
