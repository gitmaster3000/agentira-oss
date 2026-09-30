"""Local Docker deploy provider — the backend half.

The backend can't reach the host's Docker, so every docker deploy action is a
`deploy` frame to the user's daemon, and the daemon reports back on
`/api/forge/daemon/deploy-result`. These tests fake the daemon seam
(`backend.deploy.docker._send`) and drive the real REST routes, flow, repo and
Postgres. The real-Docker half lives in agentira-cli/tests/test_deploy_docker.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.db as bdb
from backend.deploy import docker as docker_mod
from backend.deploy import registry
from backend.deploy.contract import DeploymentStatus, TargetKind
from backend.forge.models import ForgeRuntime, RuntimeStatus
from backend.rest_api import app

SOURCE = "https://github.com/acme/shop.git"


@pytest.fixture
def frames(monkeypatch):
    sent: list[tuple[str, dict]] = []

    def _fake_send(runtime_id, payload):
        sent.append((runtime_id, payload))
        return True

    monkeypatch.setattr(docker_mod, "_send", _fake_send)
    return sent


@pytest.fixture
def client(seed_admin):
    _admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


@pytest.fixture
def runtime_id(pg):
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id="d-1", provider="claude", binary_path="/bin/claude",
                          status=RuntimeStatus.ONLINE)
        db.add(rt)
        db.commit()
        return rt.id


def _docker_project(client, config=None) -> str:
    pid = client.post("/api/projects", json={"name": "Shop"}).json()["id"]
    r = client.put(f"/api/projects/{pid}/deploy-settings", json={
        "kind": "docker", "config": {"source_url": SOURCE, **(config or {})}})
    assert r.status_code == 200, r.text
    return pid


def _deploy(client, pid, branch="feature/cart") -> dict:
    r = client.post(f"/api/projects/{pid}/deployments", json={"branch": branch})
    assert r.status_code == 202, r.text
    return r.json()


def _report(client, frame, **body):
    r = client.post("/api/forge/daemon/deploy-result", json={
        "daemon_id": "d-1", "deployment_id": frame["deployment_id"],
        "action": frame["action"], **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_docker_adapter_is_registered():
    assert isinstance(registry.get_adapter(TargetKind.DOCKER), docker_mod.DockerAdapter)


def test_docker_target_needs_no_key_and_reads_as_connected(client, runtime_id):
    pid = _docker_project(client)
    body = client.get(f"/api/projects/{pid}/deploy/provider").json()
    assert body["connected"] is True
    assert body["provider"] == "docker"


def test_deploy_sends_frame_to_daemon_and_row_is_queued(client, frames, runtime_id):
    pid = _docker_project(client, {"health_path": "/healthz"})
    dep = _deploy(client, pid)
    assert dep["status"] == "queued"
    assert dep["status_reason"]  # plain language, never empty

    [(rt, frame)] = frames
    assert rt == runtime_id
    assert frame["type"] == "deploy"
    assert frame["action"] == "deploy"
    assert frame["project_id"] == pid
    assert frame["branch"] == "feature/cart"
    assert frame["ref"] == "feature/cart"
    assert frame["source_url"] == SOURCE
    assert frame["config"]["health_path"] == "/healthz"
    # Handle is opaque to the client but routes back to this runtime.
    assert frame["deployment_id"].startswith(f"{runtime_id}:")


def test_daemon_result_updates_deployment_row(client, frames, runtime_id):
    pid = _docker_project(client)
    dep = _deploy(client, pid)
    frame = frames[0][1]

    _report(client, frame, status="building", logs=["Cloning feature/cart"])
    [entry] = [b for b in client.get(f"/api/projects/{pid}/deployments").json()["branches"]
               if b["branch"] == "feature/cart"]
    assert entry["deployment"]["status"] == "building"

    _report(client, frame, status="live", url="http://127.0.0.1:23456",
            logs=["Cloning feature/cart", "Built image", "Health check passed"])
    [entry] = [b for b in client.get(f"/api/projects/{pid}/deployments").json()["branches"]
               if b["branch"] == "feature/cart"]
    assert entry["deployment"]["id"] == dep["id"]
    assert entry["deployment"]["status"] == "live"
    assert entry["deployment"]["url"] == "http://127.0.0.1:23456"

    logs = client.get(f"/api/projects/{pid}/deployments/{dep['id']}/logs").json()
    assert [line["text"] for line in logs["lines"]][-1] == "Health check passed"
    assert logs["done"] is True


def test_failed_result_keeps_plain_reason(client, frames, runtime_id):
    pid = _docker_project(client)
    _deploy(client, pid)
    frame = frames[0][1]
    _report(client, frame, status="failed", detail="The app never answered on /.",
            logs=["ERROR: connection refused"])
    [entry] = [b for b in client.get(f"/api/projects/{pid}/deployments").json()["branches"]
               if b["branch"] == "feature/cart"]
    assert entry["deployment"]["status"] == "failed"
    assert entry["deployment"]["status_reason"] == "The app never answered on /."


def test_result_for_unknown_deployment_is_404(client):
    r = client.post("/api/forge/daemon/deploy-result", json={
        "deployment_id": "nope:agentira-x", "action": "deploy", "status": "live"})
    assert r.status_code == 404


def test_stop_sends_teardown_frame(client, frames, runtime_id):
    pid = _docker_project(client)
    dep = _deploy(client, pid)
    handle = frames[0][1]["deployment_id"]
    r = client.delete(f"/api/projects/{pid}/deployments/{dep['id']}")
    assert r.status_code == 204
    rt, frame = frames[-1]
    assert rt == runtime_id
    assert frame["action"] == "teardown"
    assert frame["deployment_id"] == handle


def test_redeploy_reuses_row_and_sends_new_frame(client, frames, runtime_id):
    pid = _docker_project(client)
    dep = _deploy(client, pid)
    _report(client, frames[0][1], status="live", url="http://127.0.0.1:23456")
    r = client.post(f"/api/projects/{pid}/deployments/{dep['id']}/redeploy")
    assert r.status_code == 202, r.text
    assert r.json()["id"] == dep["id"]
    assert r.json()["status"] == "queued"
    assert len(frames) == 2 and frames[1][1]["action"] == "deploy"


def test_logs_request_asks_daemon_for_fresh_lines(client, frames, runtime_id):
    pid = _docker_project(client)
    dep = _deploy(client, pid)
    _report(client, frames[0][1], status="live", url="http://127.0.0.1:1", logs=["boot"])
    client.get(f"/api/projects/{pid}/deployments/{dep['id']}/logs")
    assert frames[-1][1]["action"] == "logs"


def test_adapter_status_and_preview_url_read_last_report(client, frames, runtime_id):
    pid = _docker_project(client)
    _deploy(client, pid)
    frame = frames[0][1]
    _report(client, frame, status="live", url="http://127.0.0.1:23456")
    adapter = registry.get_adapter(TargetKind.DOCKER)
    assert adapter.status(frame["deployment_id"]) == DeploymentStatus.LIVE
    assert frames[-1][1]["action"] == "status"
    assert adapter.preview_url(frame["deployment_id"]) == "http://127.0.0.1:23456"


def test_hostile_branch_is_rejected_before_anything_is_sent(client, frames, runtime_id):
    pid = _docker_project(client)
    for bad in ("main; rm -rf /", "--upload-pack=touch /tmp/x", "a/../../b", "$(id)"):
        r = client.post(f"/api/projects/{pid}/deployments", json={"branch": bad})
        assert r.status_code == 400, bad
    assert frames == []


def test_no_daemon_online_fails_in_plain_language(client, frames, pg):
    pid = _docker_project(client)
    dep = _deploy(client, pid)
    assert dep["status"] == "failed"
    assert "computer" in dep["status_reason"].lower()
    assert frames == []
