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


class Template(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str = ""
    trigger: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    agents: list[TemplateAgent] = Field(default_factory=list)
    ac_check_types: list[ACCheckType] = Field(default_factory=list)
    conductor: ConductorConfig = Field(default_factory=ConductorConfig)

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
