"""C7b: the Conductor owns direction + epics.

A sprint-planning turn (daily at a configured time, and when a project's
queue runs dry) writes the direction if empty, keeps 1–3 epics in_progress,
and breaks in-progress epics with no open tasks into tasks.
"""
from unittest.mock import patch

import pytest

from backend import services as core_services
from backend.forge import conductor, services as forge_services
from backend.tests.test_conductor_turn_scopes import _mk_project_with_agent


@pytest.fixture(autouse=True)
def _db(pg):
    yield pg


def _send_capture():
    sent = []
    return sent, patch.object(
        forge_services, "send_runtime_message",
        side_effect=lambda aid, **kw: sent.append(kw["content"]) or {"ok": True})


def test_in_progress_epic_without_tasks_is_in_facts_and_prompt():
    _, pid, _ = _mk_project_with_agent("Spr")
    epic = core_services.create_epic(pid, "Loop v1", actor="system")
    core_services.update_epic(epic["id"], status="in_progress", actor="system")
    with patch.object(conductor, "_runtime_live", return_value=True):
        conductor.get_or_create_conductor()   # bound while its daemon was up
    facts = conductor.gather_sprint_planning_facts(pid)
    assert [e["id"] for e in facts["needs_breakdown"]] == [epic["id"]]
    sent, p = _send_capture()
    with p, patch.object(conductor, "_runtime_live", return_value=True):
        conductor.run_sprint_planning_turn()
    assert "Loop v1" in sent[0] and "SPRINT PLANNING" in sent[0]


def test_queue_dry_fires_sprint_planning_once_per_interval():
    _, pid, _ = _mk_project_with_agent("Dry")
    # Drain the board — create_project auto-seeds a "Plan this project" todo,
    # so move every task to done to make the queue genuinely dry.
    for t in core_services.list_tasks(pid, actor="system"):
        core_services.move_task(t["id"], "done", actor="system", skip_gates=True)
    with patch.object(conductor, "_runtime_live", return_value=True):
        conductor.get_or_create_conductor()   # bound while its daemon was up
    with patch.object(conductor, "run_sprint_planning_turn",
                      return_value={}) as sp, \
         patch.object(conductor, "_runtime_live", return_value=True), \
         patch.object(forge_services, "send_runtime_message", return_value={"ok": True}):
        conductor.run_planning_turn()
        conductor.run_planning_turn()
    sp.assert_called_once_with(trigger="queue_dry", project_id=pid)


def test_sprint_time_read_from_config_not_a_constant():
    _mk_project_with_agent("Cfg")
    conductor.get_or_create_conductor()
    forge_services.update_agent(
        conductor.get_or_create_conductor()["id"],
        conductor_sprint_time="05:15", conductor_sprint_min_interval_hours=9)
    cfg = conductor.get_conductor_config()
    assert cfg["sprint_time"] == "05:15"
    assert cfg["sprint_min_interval_hours"] == 9


