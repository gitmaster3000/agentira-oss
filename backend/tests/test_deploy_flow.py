"""AP-451: the deploy *flow* REST contract end-to-end.

Drives every endpoint src/api.js calls under `// Deploy` (the contract in
frontend/docs/deploy-backend-requirements.md §2) through the real router,
services gateway, DeployFlow handler, repo and persistence — with the Railway
adapter swapped for an in-memory fake so no live Railway account or token is
needed. This proves the backend implements each endpoint the frontend needs
and returns the documented shape; the live-Railway build path is exercised
through the same adapter seam but against a real account is out of scope here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.deploy import registry
from backend.deploy.contract import (
    Capability, DeploymentResult, DeploymentStatus, TargetKind)
from backend.rest_api import app


class _FakeRailway:
    """Stand-in for RailwayAdapter: deterministic, offline, no env token."""

    capabilities = frozenset({
        Capability.DEPLOY, Capability.STATUS, Capability.LOGS,
        Capability.PREVIEW_URL, Capability.TEARDOWN,
    })
    _SERVICES = [
        {"id": "svc_1", "name": "billing-api", "project": "acme",
         "type": "web service", "region": "us-west", "deployable": True},
        {"id": "svc_pg", "name": "postgres", "project": "acme",
         "type": "database", "region": "us-west", "deployable": False},
    ]

    def supports(self, capability) -> bool:
        return capability in self.capabilities

    def verify_credential(self, token):
        return (True, "authenticated as acme") if token else (False, "no token")

    def probe_key(self, token):
        if not token:
            return {"valid": False, "error": {"headline": "no key", "detail": "…"}}
        return {"valid": True, "account": "acme", "services": self._SERVICES}

    def deploy(self, target, ref) -> DeploymentResult:
        return DeploymentResult(
            deployment_id=f"rw_{ref}", status=DeploymentStatus.RUNNING,
            url=None, detail=f"Building {ref} · step 1 of 4")

    def status(self, deployment_id) -> DeploymentStatus:
        return DeploymentStatus.LIVE

    def logs(self, deployment_id) -> list[str]:
        return ["npm ci", "build ok", "listening on :8080"]

    def preview_url(self, deployment_id):
        return f"https://{deployment_id}.up.railway.app"

    def teardown(self, deployment_id) -> None:
        return None


@pytest.fixture
def fake_railway():
    """Swap the registered Railway adapter for the offline fake, restore after."""
    original = registry.get_adapter(TargetKind.RAILWAY)
    registry.register(TargetKind.RAILWAY, _FakeRailway())
    try:
        yield
    finally:
        registry.register(TargetKind.RAILWAY, original)


@pytest.fixture
def client(seed_admin):
    _admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _project(client) -> str:
    return client.post("/api/projects", json={"name": "Billing"}).json()["id"]


def _connect(client, pid) -> dict:
    r = client.post(f"/api/projects/{pid}/deploy/provider", json={
        "provider": "railway", "api_key": "rw_secret",
        "repo": "acme/billing-api", "service_id": "svc_1"})
    assert r.status_code == 201, r.text
    return r.json()


# ── provider connection ──────────────────────────────────────────────────

def test_get_provider_unconnected(client, fake_railway):
    pid = _project(client)
    r = client.get(f"/api/projects/{pid}/deploy/provider")
    assert r.status_code == 200
    assert r.json() == {"connected": False}


def test_verify_key(client, fake_railway):
    pid = _project(client)
    r = client.post(f"/api/projects/{pid}/deploy/provider/verify",
                    json={"provider": "railway", "api_key": "rw_secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["account"] == "acme"
    assert any(s["id"] == "svc_1" and s["deployable"] for s in body["services"])
    # the postgres add-on is not deployable
    assert any(s["id"] == "svc_pg" and not s["deployable"] for s in body["services"])


def test_repo_access(client, fake_railway):
    pid = _project(client)
    r = client.get(f"/api/projects/{pid}/deploy/provider/repo-access",
                   params={"provider": "railway"})
    assert r.status_code == 200
    assert r.json()["granted"] is True


def test_connect_returns_connection_and_never_leaks_key(client, fake_railway):
    pid = _project(client)
    conn = _connect(client, pid)
    assert conn["connected"] is True
    assert conn["provider"] == "railway"
    assert conn["repo"] == "acme/billing-api"
    assert conn["service_name"] == "billing-api"
    assert conn["key_valid"] is True
    # the token is write-only — no field carries it back
    assert "rw_secret" not in r_text(conn)

    # connect kicked the first deploy of main
    got = client.get(f"/api/projects/{pid}/deploy/provider").json()
    assert got["connected"] is True


def test_reverify(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    r = client.post(f"/api/projects/{pid}/deploy/provider/reverify")
    assert r.status_code == 200
    assert r.json()["connected"] is True
    assert r.json()["key_valid"] is True


def test_disconnect(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    r = client.delete(f"/api/projects/{pid}/deploy/provider")
    assert r.status_code == 204
    assert client.get(f"/api/projects/{pid}/deploy/provider").json() == {"connected": False}


# ── deployments ──────────────────────────────────────────────────────────

def test_connect_kicks_main_deployment(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    body = client.get(f"/api/projects/{pid}/deployments").json()
    branches = body["branches"]
    assert branches[0]["branch"] == "main"
    assert branches[0]["is_main"] is True
    dep = branches[0]["deployment"]
    assert dep is not None
    assert dep["status"] in ("queued", "building", "live")
    assert dep["status_reason"]  # §4: never empty
    assert dep["trigger"] == "push"


def test_create_deployment_is_idempotent_per_branch(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    first = client.post(f"/api/projects/{pid}/deployments",
                        json={"branch": "feat/metering"})
    assert first.status_code == 202
    d1 = first.json()
    assert d1["trigger"] == "preview"
    # a second call while building returns the same in-flight deployment
    d2 = client.post(f"/api/projects/{pid}/deployments",
                     json={"branch": "feat/metering"}).json()
    assert d2["id"] == d1["id"]


def test_create_without_provider_is_rejected(client, fake_railway):
    pid = _project(client)
    r = client.post(f"/api/projects/{pid}/deployments", json={"branch": "main"})
    assert r.status_code == 400


def test_redeploy(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    dep = client.post(f"/api/projects/{pid}/deployments",
                      json={"branch": "feat/x"}).json()
    r = client.post(f"/api/projects/{pid}/deployments/{dep['id']}/redeploy")
    assert r.status_code == 202
    assert r.json()["id"] == dep["id"]  # re-run in place


def test_logs_are_cursor_paginated(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    dep = client.post(f"/api/projects/{pid}/deployments",
                      json={"branch": "feat/logs"}).json()
    r = client.get(f"/api/projects/{pid}/deployments/{dep['id']}/logs",
                   params={"cursor": 0})
    assert r.status_code == 200
    page = r.json()
    assert [ln["text"] for ln in page["lines"]] == \
        ["npm ci", "build ok", "listening on :8080"]
    assert page["next_cursor"] == 3
    assert all(ln["level"] in ("error", "warn", "info", "debug") for ln in page["lines"])
    # echo the cursor back — no lines after the end
    tail = client.get(f"/api/projects/{pid}/deployments/{dep['id']}/logs",
                      params={"cursor": page["next_cursor"]}).json()
    assert tail["lines"] == []


def test_stop_preview_then_main_is_rejected(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    preview = client.post(f"/api/projects/{pid}/deployments",
                          json={"branch": "feat/stop"}).json()
    r = client.delete(f"/api/projects/{pid}/deployments/{preview['id']}")
    assert r.status_code == 204

    main = client.get(f"/api/projects/{pid}/deployments").json()["branches"][0]
    r = client.delete(f"/api/projects/{pid}/deployments/{main['deployment']['id']}")
    assert r.status_code == 409  # main is never stoppable


def test_missing_deployment_is_404(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    r = client.get(f"/api/projects/{pid}/deployments/nope/logs")
    assert r.status_code == 404


def r_text(obj) -> str:
    import json
    return json.dumps(obj)
