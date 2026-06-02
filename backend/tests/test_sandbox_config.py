"""AP-155: agent containment policy — Phase 1 config + resolver.

Phase 1 ships the data model, REST surface, resolver, and dispatch-time
env injection. Actual sandbox enforcement (claude --add-dir / bwrap /
Docker) is Phase 2.

Tests pin:
- resolver precedence (project > agent > workspace default)
- adapter-capability downshift behavior
- end-to-end: setting Profile.sandbox_mode + Project.sandbox_mode
  through the service layer and reading it back
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services  # noqa: F401 — register mappers
from backend.forge.models import ForgeRuntime, RuntimeStatus  # noqa: F401
from backend.models import Profile
from backend.sandbox import (
    SANDBOX_MODES, WORKSPACE_DEFAULT,
    is_valid_mode, resolve_mode, downshift_to_supported,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


# ── Pure resolver ────────────────────────────────────────────────────────

def test_workspace_default_when_nothing_set():
    assert resolve_mode(project_mode=None, agent_mode=None) == WORKSPACE_DEFAULT
    assert resolve_mode(project_mode="", agent_mode="") == WORKSPACE_DEFAULT


def test_agent_default_when_project_unset():
    assert resolve_mode(project_mode=None, agent_mode="strict") == "strict"


def test_project_override_beats_agent():
    assert resolve_mode(project_mode="container",
                         agent_mode="off") == "container"
    # Even when agent wants stricter, project wins — explicit override.
    assert resolve_mode(project_mode="cwd",
                         agent_mode="container") == "cwd"


def test_invalid_mode_falls_through_to_default():
    assert resolve_mode(project_mode="ranch-dressing",
                         agent_mode=None) == WORKSPACE_DEFAULT


def test_is_valid_mode_accepts_known_and_none():
    assert is_valid_mode(None) is True
    for m in SANDBOX_MODES:
        assert is_valid_mode(m) is True
    assert is_valid_mode("strictly-no") is False


# ── Adapter-capability downshift ─────────────────────────────────────────

def test_downshift_to_supported_picks_strongest_supported():
    # Docker daemon supports all four — keep requested.
    assert downshift_to_supported(
        requested="container",
        adapter_supports={"off", "cwd", "strict", "container"},
    ) == "container"
    # Mac daemon supports off+cwd — strict gets downshifted to cwd.
    assert downshift_to_supported(
        requested="strict",
        adapter_supports={"off", "cwd"},
    ) == "cwd"
    # Adapter supports nothing → returns off (workspace default).
    assert downshift_to_supported(
        requested="container",
        adapter_supports=set(),
    ) == "off"


# ── End-to-end through services ──────────────────────────────────────────

def test_project_sandbox_mode_persists_and_surfaces(test_db):
    p = core_services.create_project("SBX", actor="system")
    out = core_services.update_project(p["id"], sandbox_mode="strict")
    assert out["sandbox_mode"] == "strict"
    again = core_services.get_project(p["id"])
    assert again["sandbox_mode"] == "strict"


def test_project_sandbox_mode_empty_string_clears_override(test_db):
    p = core_services.create_project("SBX2", actor="system")
    core_services.update_project(p["id"], sandbox_mode="container")
    cleared = core_services.update_project(p["id"], sandbox_mode="")
    assert cleared["sandbox_mode"] == ""


def test_project_sandbox_mode_rejects_unknown(test_db):
    p = core_services.create_project("SBX3", actor="system")
    # Unknown values are silently ignored (validation gate in update_project).
    out = core_services.update_project(p["id"], sandbox_mode="quarantine")
    # Mode stays empty (default) — junk didn't land.
    assert out["sandbox_mode"] == ""


def test_agent_profile_sandbox_mode_persists(test_db):
    # Use update_agent path through forge — that's what Agent Settings
    # hits in the UI.
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(
        name="boxed-agent", executor_type="cli", runtime_id=rt_id,
    )
    forge_services.update_agent(agent["id"], sandbox_mode="strict")
    with test_db() as db:
        prof = db.query(Profile).filter(Profile.name == "boxed-agent").first()
        assert prof.sandbox_mode == "strict"


def test_agent_profile_sandbox_mode_clear_via_empty(test_db):
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(
        name="boxed-agent", executor_type="cli", runtime_id=rt_id,
    )
    forge_services.update_agent(agent["id"], sandbox_mode="container")
    forge_services.update_agent(agent["id"], sandbox_mode="")
    with test_db() as db:
        prof = db.query(Profile).filter(Profile.name == "boxed-agent").first()
        assert prof.sandbox_mode is None


def test_agent_update_rejects_invalid_sandbox_mode(test_db):
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(
        name="boxed-agent", executor_type="cli", runtime_id=rt_id,
    )
    with pytest.raises(ValueError):
        forge_services.update_agent(agent["id"], sandbox_mode="airgapped")


def _seed_runtime(TestSession):
    with TestSession() as db:
        rt = ForgeRuntime(daemon_id="d-sbx", provider="claude",
                          binary_path="/x", status=RuntimeStatus.ONLINE)
        db.add(rt); db.commit(); return rt.id
