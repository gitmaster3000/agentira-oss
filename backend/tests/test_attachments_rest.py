"""Regression: attachment upload + download round-trip over REST.

Guards the 401-on-download bug: the `/api/attachments/{id}/download` route
requires the bearer token, and the round-trip is byte-exact (no truncation).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.db as bdb
from backend.rest_api import app
from backend.jwt_auth import create_token

PDF_BYTES = b"%PDF-1.4\n" + bytes(range(256)) * 26  # binary, ~6.7KB


@pytest.fixture
def client(pg, tmp_path):
    storage = tmp_path / "attachments"
    from backend.models import Profile, Role
    # Seed an admin carrying the agent api_key the download-by-key test needs.
    with bdb.privileged(), bdb.SessionLocal() as db:
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        admin = Profile(name="admin", account_type="human", org_id=pg.org_id,
                        roles=[admin_role], password_hash="",
                        api_key="agentira_testkey_abc123")
        db.add(admin)
        db.commit()
        token = create_token("admin", admin.id, "admin", org_id=pg.org_id)
    with patch("backend.attachments.ATTACHMENTS_DIR", str(storage)):
        c = TestClient(app)
        c.headers["Authorization"] = f"Bearer {token}"
        c.agent_api_key = "agentira_testkey_abc123"
        yield c


def _make_task(client):
    pid = client.post("/api/projects", json={"name": "P", "description": ""}).json()["id"]
    return client.post("/api/tasks", json={"project_id": pid, "title": "T"}).json()["id"]


def test_upload_download_round_trip_is_byte_exact(client):
    tid = _make_task(client)
    up = client.post(f"/api/tasks/{tid}/attachments",
                     files={"file": ("plan.pdf", PDF_BYTES, "application/pdf")})
    assert up.status_code == 200, up.text
    att = up.json()
    assert att["size_bytes"] == len(PDF_BYTES)  # no truncation on upload

    dl = client.get(f"/api/attachments/{att['id']}/download")
    assert dl.status_code == 200, dl.text
    assert dl.content == PDF_BYTES  # byte-exact round-trip


def test_upload_persists_evidence_kind(client):
    tid = _make_task(client)
    up = client.post(
        f"/api/tasks/{tid}/attachments",
        files={"file": ("report.md", b"PASS", "text/markdown")},
        data={"kind": "test-report"},
    )
    assert up.status_code == 200, up.text
    assert up.json()["kind"] == "test-report"
    listed = client.get(f"/api/tasks/{tid}/attachments")
    assert listed.json()[0]["kind"] == "test-report"


def test_upload_rejects_unknown_evidence_kind(client):
    tid = _make_task(client)
    up = client.post(
        f"/api/tasks/{tid}/attachments",
        files={"file": ("report.md", b"PASS", "text/markdown")},
        data={"kind": "trust-me"},
    )
    assert up.status_code == 400
    assert "Unknown attachment kind" in up.text


def test_download_requires_auth(client):
    tid = _make_task(client)
    att = client.post(f"/api/tasks/{tid}/attachments",
                      files={"file": ("plan.pdf", PDF_BYTES, "application/pdf")}).json()
    # No bearer token → the route must reject, never stream the file.
    anon = TestClient(app)
    res = anon.get(f"/api/attachments/{att['id']}/download")
    assert res.status_code == 401


def test_download_accepts_agent_api_key(client):
    # Agents curl the download route with $AGENTIRA_API_KEY (not a JWT).
    tid = _make_task(client)
    att = client.post(f"/api/tasks/{tid}/attachments",
                      files={"file": ("plan.pdf", PDF_BYTES, "application/pdf")}).json()
    agent = TestClient(app)
    res = agent.get(f"/api/attachments/{att['id']}/download",
                    headers={"Authorization": f"Bearer {client.agent_api_key}"})
    assert res.status_code == 200, res.text
    assert res.content == PDF_BYTES


def _make_project(client):
    return client.post("/api/projects", json={"name": "P", "description": ""}).json()["id"]


def test_task_folder_upload_preserves_structure(client):
    tid = _make_task(client)
    res = client.post(
        f"/api/tasks/{tid}/attachments/folder",
        files=[
            ("files", ("main.py", b"m", "text/plain")),
            ("files", ("util.py", b"u", "text/plain")),
        ],
        data={"paths": ["app/main.py", "app/lib/util.py"]},
    )
    assert res.status_code == 200, res.text
    names = {r["filename"] for r in res.json()}
    assert names == {"app/main.py", "app/lib/util.py"}


def test_folder_upload_length_mismatch_400(client):
    pid = _make_project(client)
    res = client.post(
        f"/api/projects/{pid}/attachments/folder",
        files=[("files", ("a.txt", b"a", "text/plain"))],
        data={"paths": ["a.txt", "b.txt"]},
    )
    assert res.status_code == 400


def test_project_folder_upload_unknown_project_404(client):
    res = client.post(
        "/api/projects/nope/attachments/folder",
        files=[("files", ("a.txt", b"a", "text/plain"))],
        data={"paths": ["a.txt"]},
    )
    assert res.status_code == 404


def test_zip_extract_upload(client):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("proj/README.md", "# hi")
        zf.writestr("proj/src/a.py", "a=1")
    tid = _make_task(client)
    res = client.post(
        f"/api/tasks/{tid}/attachments?extract=true",
        files={"file": ("proj.zip", buf.getvalue(), "application/zip")},
    )
    assert res.status_code == 200, res.text
    names = {r["filename"] for r in res.json()}
    assert names == {"proj/README.md", "proj/src/a.py"}


def test_attachments_dir_honors_env_override():
    # Prod (Railway) points AGENTIRA_ATTACHMENTS_DIR at a persistent volume so
    # files survive redeploys — the container disk is ephemeral. No DB needed.
    import importlib
    from backend import attachments as att
    with patch.dict("os.environ", {"AGENTIRA_ATTACHMENTS_DIR": "/mnt/vol/att"}):
        reloaded = importlib.reload(att)
        assert reloaded.ATTACHMENTS_DIR == "/mnt/vol/att"
    importlib.reload(att)  # restore module default for other tests
