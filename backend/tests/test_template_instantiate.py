"""AP-4: instantiate_project_from_template — materialize a parsed
Template into a Project + agents + AC registry. Must be idempotent on
retry so a partially-failed run is safe to replay.
"""

from __future__ import annotations

import json

import pytest

import backend.db as bdb
from backend import services as core_services
import backend.forge.models  # noqa: F401 — register FK targets
from backend.template_loader import (
    ACCheckType, Template, TemplateAgent,
    instantiate_project_from_template,
)
from backend.models import Profile, Project


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _template(**overrides) -> Template:
    base = dict(
        name="production-readiness",
        version="1.0.0",
        description="Audit + harden a vibe-coded codebase.",
        columns=["backlog", "todo", "doing", "review", "done"],
        agents=[
            TemplateAgent(name="auditor", role="auditor", model="sonnet"),
            TemplateAgent(name="planner", role="planner", model="sonnet"),
        ],
        ac_check_types=[
            ACCheckType(name="lint", runner="ruff check .",
                        pass_condition="exit_code == 0"),
        ],
    )
    base.update(overrides)
    return Template(**base)


# ── happy path ───────────────────────────────────────────────────────

def test_instantiate_creates_project(test_db):
    res = instantiate_project_from_template(_template(), "Leadcore",
                                            actor="system")
    assert res["created"] is True
    assert res["project"]["name"] == "Leadcore"
    with test_db() as db:
        p = (db.query(Project)
               .filter(Project.name == "Leadcore")
               .first())
        assert p is not None
        assert p.template_name == "production-readiness"


def test_instantiate_creates_agent_rows(test_db):
    res = instantiate_project_from_template(_template(), "Leadcore",
                                            actor="system")
    assert set(res["agents_created"]) == {"auditor", "planner"}
    with test_db() as db:
        names = {p.name for p in db.query(Profile).all()}
    assert {"auditor", "planner"}.issubset(names)


def test_instantiate_stamps_ac_check_registry(test_db):
    instantiate_project_from_template(_template(), "Leadcore",
                                      actor="system")
    with test_db() as db:
        p = db.query(Project).filter(Project.name == "Leadcore").first()
        registry = json.loads(p.ac_check_types_json)
    assert len(registry) == 1
    assert registry[0]["name"] == "lint"
    assert registry[0]["runner"] == "ruff check ."


def test_instantiate_inherits_template_description(test_db):
    instantiate_project_from_template(_template(), "Leadcore",
                                      actor="system")
    with test_db() as db:
        p = db.query(Project).filter(Project.name == "Leadcore").first()
    assert "vibe-coded" in p.description


# ── idempotency ──────────────────────────────────────────────────────

def test_second_call_returns_existing_project_without_duplicating(test_db):
    """The whole point of AP-4's 'idempotent on retry' clause."""
    first = instantiate_project_from_template(_template(), "Leadcore",
                                              actor="system")
    second = instantiate_project_from_template(_template(), "Leadcore",
                                               actor="system")
    assert second["created"] is False
    assert second["project"]["id"] == first["project"]["id"]
    assert second["agents_created"] == []
    # Exactly one project, exactly the two agents we started with.
    with test_db() as db:
        assert db.query(Project).filter(Project.name == "Leadcore").count() == 1
        assert db.query(Profile).filter(
            Profile.name.in_(["auditor", "planner"])).count() == 2


def test_partial_replay_fills_in_missing_agents(test_db):
    """If an earlier run created the project but failed mid-agent-loop,
    a retry must NOT recreate the project but SHOULD create the missing
    agents. Simulate by pre-creating one agent."""
    # Pre-create "auditor" before the template runs.
    core_services.create_service_account("auditor")
    res = instantiate_project_from_template(_template(), "Leadcore",
                                            actor="system")
    assert res["created"] is True  # project itself was new
    assert res["agents_created"] == ["planner"]
    assert res["agents_skipped"] == ["auditor"]


# ── different template / same name lives independently ───────────────

def test_different_template_with_same_project_name_is_a_new_project(test_db):
    """Idempotency is keyed on (template_name, project_name) — using a
    different template against the same project name should NOT
    short-circuit to the prior project."""
    t1 = _template()
    instantiate_project_from_template(t1, "Leadcore", actor="system")
    t2 = _template(name="other-template", agents=[
        TemplateAgent(name="bot-x", role="x", model="sonnet"),
    ], ac_check_types=[])
    res = instantiate_project_from_template(t2, "Leadcore", actor="system")
    assert res["created"] is True
    assert res["project"]["id"] != \
        instantiate_project_from_template(t1, "Leadcore",
                                          actor="system")["project"]["id"]
