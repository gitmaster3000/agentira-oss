"""Regression: attachment upload + download round-trip over REST.

Guards the 401-on-download bug: the `/api/attachments/{id}/download` route
requires the bearer token, and the round-trip is byte-exact (no truncation).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
import backend.forge.models  # noqa: F401 — FK target registration
from backend.rest_api import app
from backend.jwt_auth import create_token

PDF_BYTES = b"%PDF-1.4\n" + bytes(range(256)) * 26  # binary, ~6.7KB


@pytest.fixture
def client(tmp_path):
    import backend.db as bdb
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    storage = tmp_path / "attachments"
    # Point the app's engines at the test DB but keep the real SessionLocal so
    # its tenancy event hooks (org-stamping on insert, org filter on select)
    # still fire — swapping SessionLocal out would silently drop them.
    with patch.object(bdb, "engine", engine), \
         patch.object(bdb, "app_engine", engine), \
         patch("backend.attachments.ATTACHMENTS_DIR", str(storage)):
        from backend.db import privileged
        from backend.models import Org, Profile, Role
        with privileged(), bdb.SessionLocal() as db:
            core_services._seed_defaults(db)
            org = Org(name="TestOrg")
            db.add(org)
            db.flush()
            admin_role = db.query(Role).filter(Role.name == "admin").first()
            admin = Profile(name="admin", org_id=org.id, role_id=admin_role.id,
                            password_hash="", api_key="agentira_testkey_abc123")
            db.add(admin)
            db.commit()
            token = create_token("admin", admin.id, "admin", org_id=org.id)
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
