"""AP-125: structured run artifacts.

The agent registers what it produced (PR URLs, files, reports) via the
register_run_artifact MCP tool. The Run dict surfaces the list so the
UI can render a "Here's what got built" panel without scraping chat.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _setup(TestSession):
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], project_id=project["id"],
    )
    return run["id"]


# ── happy path ───────────────────────────────────────────────────────

def test_register_returns_artifacts_list(test_db):
    rid = _setup(test_db)
    res = forge_services.register_run_artifact(
        run_id=rid, url="https://github.com/x/y/pull/42",
        label="PR #42", kind="pr",
    )
    assert res["ok"] is True
    assert res["artifacts"] == [{
        "url": "https://github.com/x/y/pull/42",
        "label": "PR #42", "kind": "pr",
    }]


def test_run_dict_surfaces_artifacts(test_db):
    """get_run includes the artifacts list so the UI can render them."""
    rid = _setup(test_db)
    forge_services.register_run_artifact(
        run_id=rid, url="file:///tmp/audit.md", label="Audit",
        kind="report",
    )
    r = forge_services.get_run(rid)
    assert r["artifacts"] == [{
        "url": "file:///tmp/audit.md", "label": "Audit", "kind": "report",
    }]


def test_run_without_artifacts_returns_empty_list(test_db):
    rid = _setup(test_db)
    assert forge_services.get_run(rid)["artifacts"] == []


def test_multiple_artifacts_appended_in_order(test_db):
    rid = _setup(test_db)
    forge_services.register_run_artifact(run_id=rid, url="a", label="A")
    forge_services.register_run_artifact(run_id=rid, url="b", label="B")
    forge_services.register_run_artifact(run_id=rid, url="c", label="C")
    arts = forge_services.get_run(rid)["artifacts"]
    assert [a["url"] for a in arts] == ["a", "b", "c"]


# ── idempotency ──────────────────────────────────────────────────────

def test_duplicate_same_url_kind_is_deduplicated(test_db):
    """Re-registering the same (url, kind) doesn't grow the list."""
    rid = _setup(test_db)
    forge_services.register_run_artifact(run_id=rid, url="x", kind="url")
    res = forge_services.register_run_artifact(run_id=rid, url="x", kind="url")
    assert res.get("deduplicated") is True
    assert len(forge_services.get_run(rid)["artifacts"]) == 1


def test_duplicate_refreshes_label(test_db):
    """Agent may polish the label on a re-register — newest wins."""
    rid = _setup(test_db)
    forge_services.register_run_artifact(run_id=rid, url="x", label="raw")
    forge_services.register_run_artifact(run_id=rid, url="x", label="polished")
    arts = forge_services.get_run(rid)["artifacts"]
    assert arts[0]["label"] == "polished"


# ── validation ───────────────────────────────────────────────────────

def test_missing_url_rejected(test_db):
    rid = _setup(test_db)
    res = forge_services.register_run_artifact(run_id=rid, url="")
    assert "url" in (res.get("error") or "").lower()


def test_unknown_kind_rejected(test_db):
    rid = _setup(test_db)
    res = forge_services.register_run_artifact(
        run_id=rid, url="x", kind="bogus",
    )
    assert "kind" in (res.get("error") or "").lower()


def test_unknown_run_returns_error(test_db):
    res = forge_services.register_run_artifact(
        run_id="does-not-exist", url="x",
    )
    assert res == {"error": "run_not_found"}


def test_artifact_cap_enforced(test_db):
    """50/run cap stops a runaway agent from filling the DB."""
    rid = _setup(test_db)
    for i in range(50):
        forge_services.register_run_artifact(
            run_id=rid, url=f"url-{i}", kind="url",
        )
    res = forge_services.register_run_artifact(
        run_id=rid, url="overflow", kind="url",
    )
    assert "cap" in (res.get("error") or "").lower()
    assert len(forge_services.get_run(rid)["artifacts"]) == 50


def test_long_fields_get_trimmed(test_db):
    rid = _setup(test_db)
    long_label = "L" * 5000
    long_url = "https://example.com/" + ("p" * 5000)
    forge_services.register_run_artifact(
        run_id=rid, url=long_url, label=long_label,
    )
    a = forge_services.get_run(rid)["artifacts"][0]
    assert len(a["label"]) <= 200
    assert len(a["url"]) <= 1000
