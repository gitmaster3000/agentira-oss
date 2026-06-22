"""AP-157: default agent templates seeded from data/templates/agents/."""

from __future__ import annotations

import json as _json

import pytest

import backend.db as bdb
from backend import agent_templates
from backend.forge import services as forge_services  # noqa: F401 — register mappers
from backend.models import Profile, Role


@pytest.fixture(autouse=True)
def test_db(pg):
    """Shared ephemeral-Postgres harness; yield the real routing sessionmaker.
    seed_all() scopes to the pinned org via the org context."""
    yield bdb.SessionLocal


# ── Discovery — pure file IO, no DB ─────────────────────────────────────

def test_discover_returns_all_shipped_templates():
    """Every YAML in data/templates/agents/ must parse."""
    names = {t["name"] for t in agent_templates.discover()}
    assert {"Conductor", "Planner", "Backend Implementer",
            "Frontend Implementer", "Reviewer", "DevOps"} <= names


def test_discover_loads_system_prompt_from_sibling_md():
    """The yaml carries config; the .md carries the prose. Loader merges."""
    conductor = agent_templates.get_template("Conductor")
    assert conductor is not None
    assert "system_prompt" in conductor
    assert "Conductor" in conductor["system_prompt"]
    assert "finish_run" in conductor["system_prompt"]


def test_discover_marks_only_conductor_as_system():
    by_name = {t["name"]: t for t in agent_templates.discover()}
    assert by_name["Conductor"].get("is_system") is True
    assert by_name["Planner"].get("is_system", False) is False
    assert by_name["Reviewer"].get("is_system", False) is False


# ── Seed — creates profiles ──────────────────────────────────────────────

def test_seed_all_creates_one_profile_per_template(test_db):
    result = agent_templates.seed_all()
    expected = {"Conductor", "Planner", "Backend Implementer",
                "Frontend Implementer", "Reviewer", "DevOps"}
    assert set(result["created"]) >= expected

    with test_db() as db:
        for name in expected:
            prof = db.query(Profile).filter(Profile.name == name).first()
            assert prof is not None, f"profile {name!r} should be seeded"
            assert prof.account_type == "agentira_agent"
            assert prof.api_key, "every agent needs an api_key"


def test_seed_all_is_idempotent(test_db):
    first = agent_templates.seed_all()
    second = agent_templates.seed_all()
    # Re-running doesn't create duplicates.
    assert second["created"] == []
    assert set(second["already_present"]) >= set(first["created"])
    with test_db() as db:
        # Exactly one Conductor profile.
        n = db.query(Profile).filter(Profile.name == "Conductor").count()
        assert n == 1


def test_seed_all_sets_is_system_only_on_conductor(test_db):
    agent_templates.seed_all()
    with test_db() as db:
        cond = db.query(Profile).filter(Profile.name == "Conductor").first()
        planner = db.query(Profile).filter(Profile.name == "Planner").first()
        assert cond.is_system is True
        assert planner.is_system is False


def test_seed_all_persists_mcp_servers_as_json(test_db):
    agent_templates.seed_all()
    with test_db() as db:
        impl = db.query(Profile).filter(
            Profile.name == "Backend Implementer"
        ).first()
        assert impl.mcp_servers is not None
        parsed = _json.loads(impl.mcp_servers)
        assert "agentira" in parsed
        assert "memory" in parsed


# ── Set-if-empty: user edits must survive ───────────────────────────────

def test_seed_all_does_not_overwrite_user_edited_system_prompt(test_db):
    agent_templates.seed_all()
    USER_PROMPT = "You are MY planner. Be brief."
    with test_db() as db:
        prof = db.query(Profile).filter(Profile.name == "Planner").first()
        prof.system_prompt = USER_PROMPT
        db.commit()

    # Re-seed (e.g. on a backend restart).
    agent_templates.seed_all()
    agent_templates.seed_all()

    with test_db() as db:
        prof = db.query(Profile).filter(Profile.name == "Planner").first()
        assert prof.system_prompt == USER_PROMPT, (
            "User-edited prompt was overwritten — prompts-as-config broken."
        )


def test_seed_all_does_not_overwrite_user_edited_model(test_db):
    agent_templates.seed_all()
    with test_db() as db:
        prof = db.query(Profile).filter(Profile.name == "DevOps").first()
        prof.model = "claude-opus-4-7"  # user upgraded
        db.commit()

    agent_templates.seed_all()

    with test_db() as db:
        prof = db.query(Profile).filter(Profile.name == "DevOps").first()
        assert prof.model == "claude-opus-4-7"


def test_seed_all_skips_when_member_role_missing(test_db):
    """Fresh DB with no roles → return empty result, don't crash.

    seed_all gates on the 'member' role (the old 'bot' role is gone)."""
    from sqlalchemy import text
    with bdb.privileged(), test_db() as db:
        db.execute(text("TRUNCATE TABLE roles CASCADE"))
        db.commit()
    out = agent_templates.seed_all()
    assert out["created"] == []
