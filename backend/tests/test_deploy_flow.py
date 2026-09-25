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


def test_repo_access_granted_when_github_says_yes(client, fake_railway, monkeypatch):
    from backend import repo_tokens
    monkeypatch.setattr(repo_tokens, "repo_access",
                        lambda repo_url, token, **k: (True, "Connected to acme/billing-api."))
    pid = _project(client)
    _connect(client, pid)
    r = client.get(f"/api/projects/{pid}/deploy/provider/repo-access",
                   params={"provider": "railway"})
    assert r.status_code == 200
    body = r.json()
    assert body["granted"] is True
    assert body["reason"]  # plain-language, never empty


def test_repo_access_denied_says_so_plainly(client, fake_railway, monkeypatch):
    from backend import repo_tokens
    called = {}

    def fake_access(repo_url, token, **k):
        called["repo_url"] = repo_url
        return False, "Can't see acme/billing-api — the token may not have access to it."

    monkeypatch.setattr(repo_tokens, "repo_access", fake_access)
    pid = _project(client)
    _connect(client, pid)
    r = client.get(f"/api/projects/{pid}/deploy/provider/repo-access",
                   params={"provider": "railway"})
    assert r.status_code == 200
    body = r.json()
    assert body["granted"] is False
    assert "can't see" in body["reason"].lower()
    assert body["install_url"]  # somewhere to go when access is missing
    # it actually probed the linked repo, not an optimistic constant
    assert called["repo_url"] == "https://github.com/acme/billing-api.git"


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
    assert "main" in r.json()["detail"].lower()  # plain-language reason


def test_missing_deployment_is_404(client, fake_railway):
    pid = _project(client)
    _connect(client, pid)
    r = client.get(f"/api/projects/{pid}/deployments/nope/logs")
    assert r.status_code == 404


# ── AP-533: silent first deploy, encryption, real branches, GH ledger ──────

class _FailingRailway(_FakeRailway):
    """Fake whose deploy raises — models a first deploy that blows up."""

    def deploy(self, target, ref) -> DeploymentResult:
        raise RuntimeError("provider connection refused")


@pytest.fixture
def failing_railway():
    original = registry.get_adapter(TargetKind.RAILWAY)
    registry.register(TargetKind.RAILWAY, _FailingRailway())
    try:
        yield
    finally:
        registry.register(TargetKind.RAILWAY, original)


def test_failed_first_deploy_is_recorded_not_swallowed(client, failing_railway):
    pid = _project(client)
    _connect(client, pid)  # connect still succeeds even though the deploy fails
    main = client.get(f"/api/projects/{pid}/deployments").json()["branches"][0]
    dep = main["deployment"]
    assert dep is not None  # the failure did NOT vanish
    assert dep["status"] == "failed"
    assert "couldn't start" in dep["status_reason"].lower()  # plain language


def test_deploy_token_encrypted_at_rest_and_never_returned(client, fake_railway):
    pid = _project(client)
    conn = _connect(client, pid)
    # never returned by the API
    assert "rw_secret" not in r_text(conn)
    reverify = client.post(f"/api/projects/{pid}/deploy/provider/reverify").json()
    assert "rw_secret" not in r_text(reverify)

    # stored ciphertext, not plaintext — but decryptable back to the original
    from backend import secret_box
    import backend.db as bdb
    from backend.models import DeployCredential
    with bdb.SessionLocal() as db:
        row = db.query(DeployCredential).filter(
            DeployCredential.kind == "railway").first()
    assert row is not None
    assert row.token != "rw_secret"
    assert secret_box.decrypt(row.token) == "rw_secret"


def test_legacy_plaintext_token_still_readable():
    """A pre-encryption plaintext value decrypts to itself (migrate-on-write)."""
    from backend import secret_box
    assert secret_box.decrypt("legacy_plaintext_token") == "legacy_plaintext_token"
    assert secret_box.decrypt(secret_box.encrypt("x")) == "x"


def test_branch_list_uses_real_repo_branches(client, fake_railway, monkeypatch):
    from backend import repo_tokens
    monkeypatch.setattr(repo_tokens, "list_repo_branches",
                        lambda repo_url, token, **k: ["main", "dev", "feat/pricing"])
    pid = _project(client)
    _connect(client, pid)  # deploys main only
    branches = client.get(f"/api/projects/{pid}/deployments").json()["branches"]
    names = [b["branch"] for b in branches]
    assert names[0] == "main"
    assert names == ["main", "dev", "feat/pricing"]
    # a real branch with no deployment yet shows deployment: null
    dev = next(b for b in branches if b["branch"] == "dev")
    assert dev["deployment"] is None


def test_github_deployments_ledger_called_on_deploy(client, fake_railway, monkeypatch):
    from backend.deploy import flow, github_deployments
    recorded = {}

    def rec_deploy(*a, **k):
        recorded["deploy"] = (a, k)
        return 42

    def rec_status(*a, **k):
        recorded["status"] = (a, k)
        return True

    monkeypatch.setattr(flow.deploy_repo, "github_token_for_project",
                        lambda db, pid: "ghp_token")
    monkeypatch.setattr(github_deployments, "record_deployment", rec_deploy)
    monkeypatch.setattr(github_deployments, "record_deployment_status", rec_status)
    pid = _project(client)
    _connect(client, pid)  # kicks the main deploy -> ledger
    assert "deploy" in recorded  # a GitHub deployment was recorded
    assert "status" in recorded  # and a status update
    # deployment id from record_deployment flows into the status call
    assert recorded["status"][0][2] == 42


def r_text(obj) -> str:
    import json
    return json.dumps(obj)
