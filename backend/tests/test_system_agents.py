"""System agents — the Conductor and the Concierge.

Both are seeded by Agentira (not user-created), marked `is_system`, and
protected from deletion. The Conductor additionally carries cadence
config (queue-tick interval + daily-report time) on its profile.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import conductor as _conductor
from backend.forge import concierge as _concierge
from backend.forge.models import ForgeRuntime, RuntimeStatus


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg


def _seed_runtime(TestSession) -> str:
    db = bdb.SessionLocal()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/claude", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    return rt_id


# ── seeding ────────────────────────────────────────────────────────────

def test_concierge_is_seeded_and_idempotent(test_db):
    a = _concierge.get_or_create_concierge()
    b = _concierge.get_or_create_concierge()
    assert a.get("id") and a["id"] == b["id"]
    assert a["name"] == _concierge.CONCIERGE_NAME


def test_conductor_and_concierge_are_marked_system(test_db):
    cond = _conductor.get_or_create_conductor()
    conc = _concierge.get_or_create_concierge()
    for sysagent in (cond, conc):
        agent = forge_services.get_agent(sysagent["id"])
        assert agent["is_system"] is True, sysagent["name"]


def test_normal_agent_is_not_system(test_db):
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(name="worker", executor_type="cli",
                                        runtime_id=rt_id)
    assert forge_services.get_agent(agent["id"])["is_system"] is False


# ── deletion protection ────────────────────────────────────────────────

def test_system_agent_cannot_be_deleted(test_db):
    cond = _conductor.get_or_create_conductor()
    with pytest.raises(ValueError, match="system agent"):
        forge_services.delete_agent(cond["id"])
    # Still there.
    assert forge_services.get_agent(cond["id"]) is not None


def test_concierge_cannot_be_deleted(test_db):
    conc = _concierge.get_or_create_concierge()
    with pytest.raises(ValueError, match="system agent"):
        forge_services.delete_agent(conc["id"])


def test_normal_agent_can_be_deleted(test_db):
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(name="worker", executor_type="cli",
                                        runtime_id=rt_id)
    assert forge_services.delete_agent(agent["id"]) is True
    assert forge_services.get_agent(agent["id"]) is None


# ── conductor cadence config ───────────────────────────────────────────

def test_conductor_config_defaults(test_db):
    _conductor.get_or_create_conductor()
    cfg = _conductor.get_conductor_config()
    assert cfg["tick_seconds"] == 60
    assert cfg["report_time"] == "09:00"
    assert cfg["report_enabled"] is True


def test_conductor_tick_is_configurable(test_db):
    cond = _conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_tick_seconds=300,
                                conductor_report_time="07:30")
    cfg = _conductor.get_conductor_config()
    assert cfg["tick_seconds"] == 300
    assert cfg["report_time"] == "07:30"


def test_conductor_tick_is_clamped_to_a_floor(test_db):
    """A sub-10s tick would hammer the DB — the config read clamps it."""
    cond = _conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_tick_seconds=2)
    assert _conductor.get_conductor_config()["tick_seconds"] == 10


def test_agent_dict_exposes_conductor_config(test_db):
    cond = _conductor.get_or_create_conductor()
    agent = forge_services.get_agent(cond["id"])
    for key in ("is_system", "conductor_tick_seconds",
                "conductor_report_time", "conductor_report_enabled"):
        assert key in agent, key


# ── workspace-wide visibility ──────────────────────────────────────────

def test_system_agent_gets_permission_wildcard(test_db):
    """A system agent must hold the '*' wildcard — otherwise it's scoped
    to its (empty) project memberships and sees nothing."""
    from backend import auth
    conc = _concierge.get_or_create_concierge()
    with forge_services._session() as db:
        assert auth.get_permissions(db, conc["name"]) == {"*"}
        assert auth.has_permission(db, conc["name"], "project.view_all")


def test_conductor_sees_projects_it_is_not_a_member_of(test_db):
    """The bug: the Conductor (member of no project) got [] from
    list_projects. With the system-agent wildcard it sees everything."""
    cond = _conductor.get_or_create_conductor()
    core_services.create_project("Workspace Project", actor="system")
    visible = core_services.list_projects(actor=cond["name"])
    assert any(p["name"] == "Workspace Project" for p in visible)


def test_normal_agent_does_not_get_the_wildcard(test_db):
    """Only system agents get '*' — a regular agent stays role-scoped."""
    from backend import auth
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(name="worker", executor_type="cli",
                                        runtime_id=rt_id)
    with forge_services._session() as db:
        assert auth.get_permissions(db, "worker") != {"*"}
