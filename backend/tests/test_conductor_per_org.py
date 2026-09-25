"""Loop v1 C2: each managed project's Conductor turn goes to ITS org's
Conductor — never whichever `Conductor` profile happens to be first."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.db import SessionLocal, privileged
from backend.forge import conductor, services as forge_services
from backend.models import Org, Profile
from backend.tests.test_conductor_turn_scopes import _mk_project_with_agent


@pytest.fixture(autouse=True)
def _conductor_runtime_live(monkeypatch):
    """Tests here cover routing/content, not delivery: treat unconnected test
    runtimes as live. Liveness itself: test_conductor_liveness.py."""
    from backend.forge import conductor as _c
    monkeypatch.setattr(_c, "_runtime_live", lambda runtime_id: True)



@pytest.fixture(autouse=True)
def _db(pg):
    yield pg


def _other_org_conductor() -> str:
    """Seed a Conductor in a second org and make it the FIRST Conductor row
    (older created_at) — the case `.first()` used to get wrong."""
    with privileged(), SessionLocal() as db:
        other = Org(name="Other")
        db.add(other)
        db.flush()
        other_id = other.id
        db.commit()
    decoy = conductor.get_or_create_conductor(org_id=other_id)
    from datetime import datetime, timezone
    with privileged(), SessionLocal() as db:
        db.get(Profile, decoy["id"]).created_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        db.commit()
    return decoy["id"]


def test_planning_turn_goes_to_project_org_conductor():
    decoy_id = _other_org_conductor()
    _mk_project_with_agent("OrgA")
    home = conductor.get_or_create_conductor()
    assert decoy_id != home["id"]

    sent: list[str] = []
    with patch.object(forge_services, "send_runtime_message",
                      side_effect=lambda aid, **kw: sent.append(aid) or {"ok": True}), \
         patch.object(conductor, "_runtime_live", return_value=True), \
         privileged():  # the scheduler runs with no org context: all orgs visible
        conductor.run_planning_turn()
    assert sent == [home["id"]]


def test_conductor_for_org_filters_by_org():
    conductor.get_or_create_conductor()
    with privileged(), SessionLocal() as db:
        p = db.query(Profile).filter(Profile.name == "Conductor").first()
        assert conductor.conductor_for_org(db, p.org_id).id == p.id
        assert conductor.conductor_for_org(db, "no-such-org") is None


def test_config_reads_the_managing_orgs_conductor():
    decoy_id = _other_org_conductor()
    _mk_project_with_agent("OrgCfg")
    home = conductor.get_or_create_conductor()
    with privileged(), SessionLocal() as db:
        db.get(Profile, decoy_id).conductor_tick_seconds = 999
        db.get(Profile, home["id"]).conductor_tick_seconds = 42
        db.commit()
    with privileged():  # scheduler view: every org's Conductor is visible
        assert conductor.get_conductor_config()["tick_seconds"] == 42
