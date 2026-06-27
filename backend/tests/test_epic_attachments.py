"""AP-351: epic-scoped attachments (upload/list/download over REST)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.db as bdb
from backend.rest_api import app
from backend.jwt_auth import create_token

PNG_BYTES = b"\x89PNG\r\n" + bytes(range(256)) * 4


@pytest.fixture
def client(pg, tmp_path):
    storage = tmp_path / "attachments"
    from backend.models import Profile, Role
    with bdb.privileged(), bdb.SessionLocal() as db:
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        admin = Profile(name="admin", account_type="human", org_id=pg.org_id,
                        roles=[admin_role], password_hash="")
        db.add(admin)
        db.commit()
        token = create_token("admin", admin.id, "admin", org_id=pg.org_id)
    with patch("backend.attachments.ATTACHMENTS_DIR", str(storage)):
        c = TestClient(app)
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def _make_epic(client):
    pid = client.post("/api/projects", json={"name": "P", "description": ""}).json()["id"]
    return client.post(f"/api/projects/{pid}/epics", json={"title": "E"}).json()["id"]


def test_epic_attachment_round_trip(client):
    eid = _make_epic(client)
    up = client.post(f"/api/epics/{eid}/attachments",
                     files={"file": ("brief.png", PNG_BYTES, "image/png")})
    assert up.status_code == 200, up.text
    att = up.json()
    assert att["epic_id"] == eid
    assert att["size_bytes"] == len(PNG_BYTES)

    listed = client.get(f"/api/epics/{eid}/attachments")
    assert listed.status_code == 200
    assert [a["id"] for a in listed.json()] == [att["id"]]

    dl = client.get(f"/api/attachments/{att['id']}/download")
    assert dl.status_code == 200
    assert dl.content == PNG_BYTES


def test_epic_attachment_unknown_epic_404(client):
    res = client.post("/api/epics/nope/attachments",
                      files={"file": ("x.txt", b"x", "text/plain")})
    assert res.status_code == 404


def test_attachment_requires_exactly_one_scope():
    from backend import attachments
    with pytest.raises(ValueError):
        attachments.add(task_id="t", epic_id="e", filename="f", file_bytes=b"x")
    with pytest.raises(ValueError):
        attachments.add(filename="f", file_bytes=b"x")
