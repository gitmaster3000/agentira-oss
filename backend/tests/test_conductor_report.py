"""The Conductor's daily report — its one scheduled LLM turn.

The queue tick is deterministic and token-free by design. The daily
report is where the LLM earns tokens: facts are gathered by scripts
(free), then handed to the Conductor agent as a single turn.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import conductor as _conductor
from backend.forge.scheduler import _parse_hhmm
from backend.forge.models import ForgeRuntime, RuntimeStatus, Run, RunStatus, RunOutcome
from backend.models import Profile


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession), \
         patch("backend.forge.digest.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _seed_runtime(TestSession) -> str:
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/claude", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    return rt_id


def _project_with_done_run(TestSession):
    """A project + a task + a completed/succeeded run, so the 24h digest
    for that project is non-empty."""
    from datetime import datetime, timezone
    proj = core_services.create_project("Reported", actor="system")
    task = core_services.create_task(proj["id"], "Ship it", actor="system")
    bot = core_services.create_service_account("worker")
    with forge_services._session() as db:
        db.add(Run(id=uuid.uuid4().hex[:12], agent_id=bot["id"],
                   task_id=task["id"], project_id=proj["id"],
                   status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                   finished_at=datetime.now(timezone.utc)))
        db.commit()
    return proj["id"]


# ── _parse_hhmm ────────────────────────────────────────────────────────

def test_parse_hhmm_valid():
    assert _parse_hhmm("07:30") == (7, 30)
    assert _parse_hhmm("00:00") == (0, 0)
    assert _parse_hhmm("23:59") == (23, 59)


def test_parse_hhmm_bad_input_falls_back():
    assert _parse_hhmm("garbage") == (9, 0)
    assert _parse_hhmm("99:99") == (9, 0)
    assert _parse_hhmm("") == (9, 0)


# ── fact gathering ─────────────────────────────────────────────────────

def test_gather_report_facts_includes_active_project(test_db):
    _project_with_done_run(test_db)
    facts = _conductor.gather_report_facts()
    assert "projects" in facts and "survey" in facts
    names = [p["project"] for p in facts["projects"]]
    assert "Reported" in names
    rep = next(p for p in facts["projects"] if p["project"] == "Reported")
    assert rep["counts"]["done"] == 1


def test_gather_report_facts_skips_silent_projects(test_db):
    # A project with no runs at all — must not clutter the report.
    core_services.create_project("Silent", actor="system")
    facts = _conductor.gather_report_facts()
    assert "Silent" not in [p["project"] for p in facts["projects"]]


def test_compose_report_prompt_renders_facts(test_db):
    _project_with_done_run(test_db)
    facts = _conductor.gather_report_facts()
    prompt = _conductor._compose_report_prompt(facts)
    assert "DAILY REPORT" in prompt
    assert "Reported" in prompt
    # The report is dispatched as an executive HTML fragment.
    assert "HTML fragment" in prompt
    assert "<section" in prompt
    assert "Today's priorities" in prompt


# ── run_daily_report ───────────────────────────────────────────────────

def test_daily_report_skipped_when_conductor_has_no_runtime(test_db):
    _conductor.get_or_create_conductor()  # no runtime registered
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = _conductor.run_daily_report()
    assert result.get("skipped") == "no_runtime"
    assert calls == []


def test_daily_report_skipped_when_disabled(test_db):
    _seed_runtime(test_db)
    cond = _conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_report_enabled=False)
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = _conductor.run_daily_report()
    assert result.get("skipped") == "report_disabled"
    assert calls == []


def test_daily_report_dispatches_an_llm_turn(test_db):
    _seed_runtime(test_db)
    cond = _conductor.get_or_create_conductor()
    _project_with_done_run(test_db)
    calls = []

    def fake_send(agent_id, *, content, scope_key=None, **kw):
        calls.append({"agent_id": agent_id, "content": content,
                      "scope_key": scope_key})
        return {"ok": True}

    with patch.object(forge_services, "send_runtime_message", fake_send):
        result = _conductor.run_daily_report()

    assert result.get("ok") is True
    assert len(calls) == 1
    assert calls[0]["agent_id"] == cond["id"]
    assert calls[0]["scope_key"] == "chat:default"
    assert "DAILY REPORT" in calls[0]["content"]
    # The report result is observable via get_last_report.
    assert _conductor.get_last_report().get("ok") is True
