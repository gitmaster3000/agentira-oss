"""AP-107: read-only Run-investigation MCP service layer.

`get_run_detail`, `list_run_events`, `get_run_diagnostics` back the three
prod-safe MCP tools that let an agent post-mortem a Run without direct
DB / container access. RBAC: the actor must be a member of the run's
project (or hold the project.view_all wildcard).
"""

from __future__ import annotations

import json

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent, AgentMessage, ForgeRuntime, MessageRole, Run, RunOutcome,
    RunStatus, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg


def _seed_runtime() -> str:
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude",
                          binary_path="/tmp/claude", status=RuntimeStatus.ONLINE)
        db.add(rt)
        db.commit()
        return rt.id


def _seed_scenario():
    """One project with member 'alice', non-member 'bob', and a finished
    Run owned by an agent on that project."""
    core_services.create_service_account("alice")
    core_services.create_service_account("bob")
    rt_id = _seed_runtime()
    project = core_services.create_project("P", actor="alice")
    agent = forge_services.create_agent(name="worker", executor_type="cli",
                                        runtime_id=rt_id)
    with forge_services._session() as db:
        r = Run(agent_id=agent["id"], project_id=project["id"],
                status=RunStatus.COMPLETED,
                outcome=RunOutcome.SUCCEEDED,
                summary="shipped the change",
                error=None)
        db.add(r)
        db.commit()
        run_id = r.id
    return {"project_id": project["id"], "agent_id": agent["id"],
            "run_id": run_id}


def _add_events(run_id, agent_id, *triples):
    """Append a sequence of (role, tool_name, content) events to a run."""
    with forge_services._session() as db:
        for role, tool, content in triples:
            db.add(AgentMessage(
                agent_id=agent_id, run_id=run_id, role=role,
                tool_name=tool, content=content,
            ))
        db.commit()


# ── get_run_detail ────────────────────────────────────────────────────

def test_get_run_detail_returns_run_shape(test_db):
    s = _seed_scenario()
    d = forge_services.get_run_detail(s["run_id"], actor="alice")
    # Spec'd fields the investigator needs.
    for key in ("id", "agent_id", "project_id", "status", "outcome",
                "summary", "duration_ms", "input_tokens", "output_tokens",
                "cost_usd", "workdir", "diff_stat", "error", "session_id"):
        assert key in d, key
    assert d["id"] == s["run_id"]
    assert d["status"] == "completed"
    assert d["outcome"] == "succeeded"
    assert d["summary"] == "shipped the change"


def test_get_run_detail_unknown_id_returns_error_dict(test_db):
    _seed_scenario()
    out = forge_services.get_run_detail("does-not-exist", actor="alice")
    assert out == {"error": "run_not_found"}


# ── RBAC ───────────────────────────────────────────────────────────────

def test_get_run_detail_denies_non_member(test_db):
    s = _seed_scenario()
    with pytest.raises(PermissionError):
        forge_services.get_run_detail(s["run_id"], actor="bob")


def test_get_run_detail_allows_system_actor(test_db):
    """The literal 'system' actor (and any is_system profile) wildcards
    project.view_all and may investigate any run."""
    s = _seed_scenario()
    d = forge_services.get_run_detail(s["run_id"], actor="system")
    assert d["id"] == s["run_id"]


# ── list_run_events ────────────────────────────────────────────────────

def test_list_run_events_returns_role_tool_content(test_db):
    s = _seed_scenario()
    _add_events(
        s["run_id"], s["agent_id"],
        (MessageRole.USER, "", "do the thing"),
        (MessageRole.ASSISTANT, "", "starting"),
        (MessageRole.TOOL, "Bash", "ran cmd"),
    )
    out = forge_services.list_run_events(s["run_id"], actor="alice")
    assert out["total"] == 3
    assert len(out["events"]) == 3
    roles = [e["role"] for e in out["events"]]
    assert roles == ["user", "assistant", "tool"]
    assert out["events"][2]["tool_name"] == "Bash"


def test_list_run_events_paginates(test_db):
    s = _seed_scenario()
    _add_events(s["run_id"], s["agent_id"], *[
        (MessageRole.ASSISTANT, "", f"msg-{i}") for i in range(7)
    ])
    page1 = forge_services.list_run_events(s["run_id"], actor="alice",
                                           limit=3, offset=0)
    page2 = forge_services.list_run_events(s["run_id"], actor="alice",
                                           limit=3, offset=3)
    assert page1["total"] == 7 and len(page1["events"]) == 3
    assert len(page2["events"]) == 3
    assert page1["events"][0]["content"] != page2["events"][0]["content"]


def test_list_run_events_caps_content(test_db):
    s = _seed_scenario()
    big = "x" * 20_000
    _add_events(s["run_id"], s["agent_id"],
                (MessageRole.TOOL, "Read", big))
    out = forge_services.list_run_events(s["run_id"], actor="alice")
    ev = out["events"][0]
    assert len(ev["content"]) < len(big)
    assert ev["content"].endswith("…[truncated]")


def test_list_run_events_denies_non_member(test_db):
    s = _seed_scenario()
    with pytest.raises(PermissionError):
        forge_services.list_run_events(s["run_id"], actor="bob")


def test_list_run_events_caps_limit_at_500(test_db):
    s = _seed_scenario()
    out = forge_services.list_run_events(s["run_id"], actor="alice",
                                         limit=9999)
    assert out["limit"] == 500


# ── get_run_diagnostics ────────────────────────────────────────────────

def test_get_run_diagnostics_reads_persisted_blob(test_db):
    s = _seed_scenario()
    diag = {"exit_code": 1, "stderr_tail": "boom\nnot found",
            "last_events_tail": [{"role": "tool", "content": "x"}],
            "captured_at": "2025-01-01T00:00:00Z"}
    # Persist via the daemon-facing path so we exercise complete_trigger's
    # new `diagnostics` parameter (the real production code path).
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t1", run_id=s["run_id"],
        success=False, error="subprocess exited with code 1",
        diagnostics=diag,
    )
    out = forge_services.get_run_diagnostics(s["run_id"], actor="alice")
    assert out["exit_code"] == 1
    assert "boom" in out["stderr_tail"]
    assert out["last_events_tail"][0]["role"] == "tool"
    assert out["agent_summary"] == "shipped the change"


def test_get_run_diagnostics_no_blob_is_safe(test_db):
    s = _seed_scenario()
    out = forge_services.get_run_diagnostics(s["run_id"], actor="alice")
    assert out["exit_code"] is None
    assert out["stderr_tail"] == ""
    assert out["last_events_tail"] == []


def test_status_vs_outcome_flags_disagreement(test_db):
    s = _seed_scenario()
    # Force the run into a contradictory state: process FAILED but the
    # agent declared SUCCEEDED. Should flag as disagreement.
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        r.status = RunStatus.FAILED
        r.outcome = RunOutcome.SUCCEEDED
        db.commit()
    out = forge_services.get_run_diagnostics(s["run_id"], actor="alice")
    assert out["status_vs_outcome"] == "disagree"


def test_status_vs_outcome_agrees_on_clean_success(test_db):
    s = _seed_scenario()
    out = forge_services.get_run_diagnostics(s["run_id"], actor="alice")
    assert out["status_vs_outcome"] == "agree"


def test_get_run_diagnostics_denies_non_member(test_db):
    s = _seed_scenario()
    with pytest.raises(PermissionError):
        forge_services.get_run_diagnostics(s["run_id"], actor="bob")


# ── diagnostics blob trimming ──────────────────────────────────────────

def test_diagnostics_blob_is_capped(test_db):
    s = _seed_scenario()
    diag = {"exit_code": 1, "stderr_tail": "x" * 200_000}
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t2", run_id=s["run_id"],
        success=False, diagnostics=diag,
    )
    with forge_services._session() as db:
        raw = db.query(Run).filter(Run.id == s["run_id"]).first().diagnostics_json
    assert raw is not None
    assert len(raw) <= 50_000
    parsed = json.loads(raw)
    assert parsed["exit_code"] == 1
    assert len(parsed["stderr_tail"]) < 200_000
