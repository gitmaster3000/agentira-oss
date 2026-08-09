"""AP-280: MCP attachment tools proxy to the backend REST API.

MCP and backend are separate Railway services with separate filesystems, so
MCP must not write/read attachment bytes on its own disk. These tests cover:
- `create_attachment` POSTs to the backend when AGENTIRA_API_BASE_URL is set
  (bytes land via the REST route, no direct in-process write).
- task, project, and epic scopes select their matching REST route.
- `read_attachment` inlines text it fetches over HTTP when the bytes
  aren't on the local disk (served_over_http path).
- `delete_attachment` removes bytes through the backend REST route.
- `list_for_task` resolves a task key (e.g. 'AP-1') to the internal id.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.db as bdb
from backend import attachments as att
from backend.rest_api import app
from backend import mcp_server


@pytest.fixture
def env(pg, tmp_path):
    storage = tmp_path / "attachments"
    from backend.models import Profile, Role
    # Seed an admin carrying the agent api_key the MCP proxy authenticates with.
    with bdb.privileged(), bdb.SessionLocal() as db:
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        admin = Profile(name="admin", account_type="human", org_id=pg.org_id,
                        roles=[admin_role], password_hash="",
                        api_key="agentira_testkey_abc123")
        db.add(admin)
        db.commit()
    with patch("backend.attachments.ATTACHMENTS_DIR", str(storage)):
        client = TestClient(app)
        client.headers["Authorization"] = "Bearer agentira_testkey_abc123"
        yield client, pg.org_id


def _make_task(client):
    pid = client.post("/api/projects", json={"name": "P", "description": ""}).json()["id"]
    return client.post("/api/tasks", json={"project_id": pid, "title": "T"}).json()


def _route_httpx_to(client, base="http://test-backend"):
    """Patch mcp_server's httpx calls onto the in-process REST TestClient so the
    proxy logic runs for real against the backend, minus the network hop."""
    def fake_post(url, headers=None, files=None, timeout=None):
        return client.post(url.replace(base, ""), headers=headers, files=files)

    def fake_get(url, headers=None, timeout=None):
        return client.get(url.replace(base, ""), headers=headers)

    def fake_delete(url, headers=None, timeout=None):
        return client.delete(url.replace(base, ""), headers=headers)

    import httpx
    return patch.dict(os.environ, {"AGENTIRA_API_BASE_URL": base}), \
        patch.object(httpx, "post", fake_post), \
        patch.object(httpx, "get", fake_get), \
        patch.object(httpx, "delete", fake_delete)


def test_create_attachment_proxies_to_backend(env):
    client, org_id = env
    task = _make_task(client)
    env_p, post_p, get_p, delete_p = _route_httpx_to(client)
    mcp_server.token_ctx.set("agentira_testkey_abc123")
    with env_p, post_p, get_p, delete_p:
        out = asyncio.run(mcp_server.create_attachment(
            task_id=task["id"], filename="note.txt", content="hello forge"))
    assert out["filename"] == "note.txt"
    assert out["task_id"] == task["id"]
    # Bytes went through the REST route → downloadable over REST (no 404).
    dl = client.get(f"/api/attachments/{out['id']}/download")
    assert dl.status_code == 200
    assert dl.content == b"hello forge"


def test_read_attachment_inlines_proxied_bytes(env):
    client, org_id = env
    task = _make_task(client)
    a = att.add(task_id=task["id"], filename="spec.txt",
                file_bytes=b"remote text", content_type="text/plain")
    # Simulate "bytes not on this container's disk": drop the local file so
    # read_text falls into the served_over_http branch.
    os.remove(att.get(a["id"])[1])
    with patch.object(mcp_server, "_proxy_fetch_bytes", lambda _id: b"remote text"):
        out = asyncio.run(mcp_server.read_attachment(attachment_id=a["id"]))
    assert out["content"] == "remote text"
    assert "served_over_http" not in out


@pytest.mark.parametrize("owner_kind", ["task", "project", "epic"])
def test_scoped_crd_uses_backend_routes(env, owner_kind):
    client, org_id = env
    project = client.post(
        "/api/projects", json={"name": "Scoped", "description": ""},
    ).json()
    if owner_kind == "task":
        owner = client.post(
            "/api/tasks",
            json={"project_id": project["id"], "title": "Scoped task"},
        ).json()
    elif owner_kind == "epic":
        owner = client.post(
            f"/api/projects/{project['id']}/epics",
            json={"title": "Scoped epic"},
        ).json()
    else:
        owner = project

    owner_args = {f"{owner_kind}_id": owner["id"]}
    env_p, post_p, get_p, delete_p = _route_httpx_to(client)
    mcp_server.token_ctx.set("agentira_testkey_abc123")
    with env_p, post_p, get_p, delete_p:
        created = asyncio.run(mcp_server.create_attachment(
            filename=f"{owner_kind}.txt",
            content=f"{owner_kind} content",
            content_type="text/plain",
            **owner_args,
        ))
        listed = asyncio.run(mcp_server.read_attachment(**owner_args))
        deleted = asyncio.run(mcp_server.delete_attachment(created["id"]))

    assert created[f"{owner_kind}_id"] == owner["id"]
    assert [row["id"] for row in listed] == [created["id"]]
    assert deleted is True
    assert client.get(
        f"/api/attachments/{created['id']}/download",
    ).status_code == 404


def test_list_for_task_resolves_task_key(env):
    client, org_id = env
    task = _make_task(client)
    att.add(task_id=task["id"], filename="x.txt", file_bytes=b"hi",
            content_type="text/plain")
    rows = att.list_for_task(task["key"])  # human key, not internal id
    assert len(rows) == 1
    assert rows[0]["filename"] == "x.txt"
