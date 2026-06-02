"""AP-152: project + task attachments via the shared `Attachment` table.

Covers:
- `add()` rejects neither/both of (task_id, project_id) — XOR enforced in
  app code since DB nullability allows both.
- `list_for_project` inlines text/* under the byte budget; binary is left
  without `inline_text` but always has a `download_url`.
- `read_text` returns text inline; binary returns a download hint with
  `api_key_env: AGENTIRA_API_KEY` (no base64).
- The `services.add_attachment` shim still works for task uploads.
- Storage layout: task → `<task_id>/...`; project → `projects/<pid>/...`.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend import attachments as att


@pytest.fixture(autouse=True)
def test_db_and_storage(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    storage = tmp_path / "attachments"
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.attachments.SessionLocal", TestSession), \
         patch("backend.attachments.ATTACHMENTS_DIR", str(storage)):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _make_project(name: str = "P1") -> dict:
    return core_services.create_project(name, actor="system")


def _make_task(project_id: str, title: str = "T1") -> dict:
    return core_services.create_task(
        project_id=project_id, title=title, description="", actor="system",
    )


# ── XOR validation ──────────────────────────────────────────────────────

def test_add_requires_exactly_one_owner():
    p = _make_project()
    t = _make_task(p["id"])

    with pytest.raises(ValueError):
        att.add(filename="x.txt", file_bytes=b"hi", content_type="text/plain")

    with pytest.raises(ValueError):
        att.add(task_id=t["id"], project_id=p["id"], filename="x.txt",
                file_bytes=b"hi", content_type="text/plain")


# ── Project attachments + inline_text ──────────────────────────────────

def test_list_for_project_inlines_small_text_files():
    p = _make_project()
    att.add(project_id=p["id"], filename="brief.md", file_bytes=b"# Brief\n\nDo X.",
            content_type="text/markdown")
    att.add(project_id=p["id"], filename="logo.png",
            file_bytes=b"\x89PNG\r\n\x1a\n\x00\x00",
            content_type="image/png")

    rows = att.list_for_project(p["id"])
    by_name = {r["filename"]: r for r in rows}

    assert by_name["brief.md"]["inline_text"].startswith("# Brief")
    assert "inline_text" not in by_name["logo.png"]
    # Both always carry a download_url for the binary fallback.
    assert by_name["brief.md"]["download_url"].endswith("/download")
    assert by_name["logo.png"]["download_url"].endswith("/download")


def test_list_for_project_respects_inline_budget():
    p = _make_project()
    big = ("x" * 1000).encode()
    att.add(project_id=p["id"], filename="big.txt", file_bytes=big,
            content_type="text/plain")
    rows = att.list_for_project(p["id"], inline_text_max=500)
    assert "inline_text" not in rows[0]


# ── read_text: no base64 ───────────────────────────────────────────────

def test_read_text_returns_text_inline_for_text_files():
    p = _make_project()
    a = att.add(project_id=p["id"], filename="spec.txt",
                file_bytes=b"hello world", content_type="text/plain")
    out = att.read_text(a["id"])
    assert out["content"] == "hello world"
    assert "content_base64" not in out


def test_read_text_returns_download_hint_for_binary():
    p = _make_project()
    a = att.add(project_id=p["id"], filename="logo.png",
                file_bytes=b"\x89PNG\r\n\x1a\n\x00",
                content_type="image/png")
    out = att.read_text(a["id"])
    assert "content" not in out
    assert out["api_key_env"] == "AGENTIRA_API_KEY"
    assert out["download_url"].endswith("/download")
    assert "curl" in out["hint"]


# ── Storage layout ─────────────────────────────────────────────────────

def test_storage_layout_separates_task_and_project():
    p = _make_project()
    t = _make_task(p["id"])
    a_task = att.add(task_id=t["id"], filename="t.txt", file_bytes=b"t",
                     content_type="text/plain")
    a_proj = att.add(project_id=p["id"], filename="p.txt", file_bytes=b"p",
                     content_type="text/plain")

    # Task path: <ATTACHMENTS_DIR>/<task_id>/...
    assert f"/{t['id']}/" in att.get(a_task["id"])[1]
    # Project path: <ATTACHMENTS_DIR>/projects/<project_id>/...
    assert f"/projects/{p['id']}/" in att.get(a_proj["id"])[1]


# ── Back-compat shim through services.py ──────────────────────────────

def test_services_add_attachment_shim_still_works_for_tasks():
    p = _make_project()
    t = _make_task(p["id"])
    out = core_services.add_attachment(
        task_id=t["id"], filename="x.txt", file_bytes=b"shim",
        content_type="text/plain", uploaded_by="alice",
    )
    assert out["task_id"] == t["id"]
    assert out["project_id"] is None
    listed = core_services.list_attachments(t["id"])
    assert len(listed) == 1
    assert listed[0]["filename"] == "x.txt"


# ── Delete removes row + file ──────────────────────────────────────────

def test_delete_removes_row_and_file():
    p = _make_project()
    a = att.add(project_id=p["id"], filename="x.txt", file_bytes=b"bye",
                content_type="text/plain")
    _, path = att.get(a["id"])
    assert os.path.exists(path)
    assert att.delete(a["id"]) is True
    assert not os.path.exists(path)
    assert att.get(a["id"]) is None
