"""Project deploy settings: target selection + cloud-provider credential.

Covers the REST surface and the DeploymentManager rules — unknown kinds are
rejected, the credential is probe-verified through the target's adapter, and the
token value is never serialized back (only presence + cached validity). The
adapter probe is stubbed so the suite stays offline.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    """Authed-as-admin REST client on the shared ephemeral-Postgres harness."""
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    yield c


def _make_project(client):
    return client.post("/api/projects", json={"name": "P"}).json()["id"]


class _StubAdapter:
    """Stands in for a real DeployAdapter; returns a canned verify result."""
    def __init__(self, result, probe=None):
        self._result = result
        self._probe = probe

    def verify_credential(self, token):
        return self._result

    def probe_key(self, token):
        return self._probe


# ── target ────────────────────────────────────────────────────────────────

def test_default_target_is_railway(client):
    pid = _make_project(client)
    body = client.get(f"/api/projects/{pid}/deploy-settings").json()
    assert body["target"]["kind"] == "railway"
    assert body["target"]["config"] == {}
    assert body["credential"]["has_token"] is False


def test_set_target_stores_kind_and_opaque_config(client):
    pid = _make_project(client)
    res = client.put(f"/api/projects/{pid}/deploy-settings",
                     json={"kind": "docker", "config": {"port": 8080}})
    assert res.status_code == 200, res.text
    assert res.json()["target"] == {"kind": "docker", "config": {"port": 8080}}
    # persisted
    got = client.get(f"/api/projects/{pid}/deploy-settings").json()
    assert got["target"]["config"] == {"port": 8080}


def test_unknown_kind_rejected(client):
    pid = _make_project(client)
    res = client.put(f"/api/projects/{pid}/deploy-settings",
                     json={"kind": "heroku", "config": {}})
    assert res.status_code == 400
    assert "unknown deploy target kind" in res.json()["detail"]


# ── credential ──────────────────────────────────────────────────────────────

def test_set_credential_verifies_via_adapter_and_never_leaks_token(client):
    pid = _make_project(client)
    with patch("backend.deploy.manager.registry.get_adapter",
               return_value=_StubAdapter((True, "authenticated"))):
        res = client.put(f"/api/projects/{pid}/deploy-credential",
                         json={"kind": "railway", "token": "secret-tok"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_token"] is True
    assert body["valid"] is True
    assert body["detail"] == "authenticated"
    assert "token" not in body
    assert "secret-tok" not in res.text


def test_invalid_token_stored_as_invalid(client):
    pid = _make_project(client)
    with patch("backend.deploy.manager.registry.get_adapter",
               return_value=_StubAdapter((False, "401 unauthorized"))):
        body = client.put(f"/api/projects/{pid}/deploy-credential",
                          json={"kind": "railway", "token": "bad"}).json()
    assert body["has_token"] is True
    assert body["valid"] is False


def test_no_adapter_leaves_validity_unknown(client):
    pid = _make_project(client)
    with patch("backend.deploy.manager.registry.get_adapter",
               side_effect=LookupError):
        body = client.put(f"/api/projects/{pid}/deploy-credential",
                          json={"kind": "gcp_cloud_run", "token": "tok"}).json()
    assert body["has_token"] is True
    assert body["valid"] is None
    assert body["detail"] == "no adapter for this provider yet"


# ── key verify (the endpoint the connect wizard calls) ──────────────────────

VERIFIED = {
    "valid": True,
    "account": "ops@agentira.dev",
    "services": [{"id": "svc_1", "name": "flowty-api", "type": "web service",
                  "region": None, "deployable": True}],
}


def test_wizard_can_verify_a_key(client):
    """AP-446: the Deploy wizard posts here. The route did not exist, so the
    frontend's Verify step failed for every key, valid or not."""
    pid = _make_project(client)
    with patch("backend.deploy.manager.registry.get_adapter",
               return_value=_StubAdapter(None, probe=VERIFIED)):
        res = client.post(f"/api/projects/{pid}/deploy/provider/verify",
                          json={"provider": "railway", "api_key": "rw_key"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["valid"] is True
    assert body["account"] == "ops@agentira.dev"
    assert body["services"][0]["deployable"] is True
    assert "rw_key" not in res.text  # write-only, never echoed back


def test_bad_key_is_a_200_with_an_inline_error(client):
    """Contract: an invalid key is a result the wizard renders, not a 4xx."""
    pid = _make_project(client)
    rejected = {"valid": False, "error": {"headline": "Railway rejected this key",
                                          "detail": "It may be expired."}}
    with patch("backend.deploy.manager.registry.get_adapter",
               return_value=_StubAdapter(None, probe=rejected)):
        res = client.post(f"/api/projects/{pid}/deploy/provider/verify",
                          json={"provider": "railway", "api_key": "bad"})

    assert res.status_code == 200, res.text
    assert res.json()["valid"] is False
    assert res.json()["error"]["headline"]


def test_verify_rejects_a_provider_we_cannot_connect(client):
    pid = _make_project(client)
    with patch("backend.deploy.manager.registry.get_adapter",
               side_effect=LookupError):
        res = client.post(f"/api/projects/{pid}/deploy/provider/verify",
                          json={"provider": "gcp_cloud_run", "api_key": "k"})

    assert res.status_code == 400
    assert "cannot be connected yet" in res.json()["detail"]


def test_verify_requires_a_key(client):
    pid = _make_project(client)
    res = client.post(f"/api/projects/{pid}/deploy/provider/verify",
                      json={"provider": "railway", "api_key": "  "})
    assert res.status_code == 400
    assert "api_key is required" in res.json()["detail"]


def test_empty_token_clears_credential(client):
    pid = _make_project(client)
    with patch("backend.deploy.manager.registry.get_adapter",
               return_value=_StubAdapter((True, "ok"))):
        client.put(f"/api/projects/{pid}/deploy-credential",
                   json={"kind": "railway", "token": "tok"})
    cleared = client.put(f"/api/projects/{pid}/deploy-credential",
                         json={"kind": "railway", "token": ""}).json()
    assert cleared["has_token"] is False
    assert cleared["valid"] is None
    assert cleared["detail"] == "cleared"
