"""AP-157: default agent templates seeded from data/templates/agents/."""

from __future__ import annotations

import json as _json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import agent_templates
from backend import services as core_services
from backend.forge import services as forge_services  # noqa: F401 — register mappers
from backend.models import Profile, Role


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.agent_templates.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


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
        bot = db.query(Role).filter(Role.name == "bot").first()
        for name in expected:
            prof = db.query(Profile).filter(Profile.name == name).first()
            assert prof is not None, f"profile {name!r} should be seeded"
            assert prof.role_id == bot.id
            assert prof.api_key, "every bot needs an api_key"


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


def test_seed_all_skips_when_bot_role_missing(test_db):
    """Fresh DB with no roles → return empty result, don't crash."""
    with test_db() as db:
        db.query(Profile).filter(Profile.role_id != None).delete()  # noqa: E711
        db.query(Role).delete()
        db.commit()
    out = agent_templates.seed_all()
    assert out["created"] == []
