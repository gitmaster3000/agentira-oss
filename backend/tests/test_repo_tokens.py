"""AP-302: git access tokens for project repos and agent profiles.

Covers the REST surface (set / re-check / clear) plus that the token value
is never serialized — only presence + cached validity. GitHub verification
is mocked so the suite stays offline.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import services as core_services
from backend.rest_api import app
from backend import repo_tokens


@pytest.fixture
def client(seed_admin):
    """Authed-as-admin REST client on the shared ephemeral-Postgres harness."""
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    c.admin_id = admin_id
    yield c


def _make_project_with_repo(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    client.post(f"/api/projects/{pid}/repos", json={
        "name": "backend", "repo_url": "https://github.com/acme/widgets.git",
    })
    return pid


# ── parse_github_repo ────────────────────────────────────────────────────

def test_parse_github_repo():
    assert repo_tokens.parse_github_repo(
        "https://github.com/acme/widgets.git") == ("acme", "widgets")
    assert repo_tokens.parse_github_repo(
        "git@github.com:acme/widgets.git") == ("acme", "widgets")
    assert repo_tokens.parse_github_repo("https://gitlab.com/a/b") is None
    assert repo_tokens.parse_github_repo(None) is None


# ── project repo token ───────────────────────────────────────────────────

def test_set_repo_token_probes_and_never_leaks_value(client):
    pid = _make_project_with_repo(client)
    with patch.object(repo_tokens, "verify_git_token",
                      return_value=(True, "ok")):
        res = client.put(f"/api/projects/{pid}/repos/backend/token",
                         json={"token": "ghp_secret"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_token"] is True
    assert body["token_valid"] is True
    assert body["token_checked_at"]
    # The token value must not appear anywhere in the response.
    assert "ghp_secret" not in res.text


def test_recheck_updates_validity(client):
    pid = _make_project_with_repo(client)
    with patch.object(repo_tokens, "verify_git_token",
                      return_value=(True, "ok")):
        client.put(f"/api/projects/{pid}/repos/backend/token",
                   json={"token": "ghp_secret"})
    # Token later revoked → re-check flips validity to False.
    with patch.object(repo_tokens, "verify_git_token",
                      return_value=(False, "rejected")):
        res = client.post(f"/api/projects/{pid}/repos/backend/token/check")
    assert res.status_code == 200
    assert res.json()["token_valid"] is False


def test_clear_repo_token(client):
    pid = _make_project_with_repo(client)
    with patch.object(repo_tokens, "verify_git_token",
                      return_value=(True, "ok")):
        client.put(f"/api/projects/{pid}/repos/backend/token",
                   json={"token": "ghp_secret"})
    res = client.put(f"/api/projects/{pid}/repos/backend/token",
                     json={"token": ""})
    body = res.json()
    assert body["has_token"] is False
    assert body["token_valid"] is None


def test_set_token_unknown_repo_404(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    res = client.put(f"/api/projects/{pid}/repos/ghost/token",
                     json={"token": "x"})
    assert res.status_code == 404


# ── profile git token ────────────────────────────────────────────────────

def test_profile_git_token_set_and_check(client):
    pid = client.admin_id
    with patch.object(repo_tokens, "verify_git_token",
                      return_value=(True, "ok")):
        res = client.put(f"/api/profiles/{pid}/git-token",
                         json={"token": "ghp_personal"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_git_token"] is True
    assert body["git_token_valid"] is True
    assert "ghp_personal" not in res.text


# ── dispatch resolution ──────────────────────────────────────────────────

def test_resolve_git_token_repo_wins_over_profile(client):
    pid = _make_project_with_repo(client)
    with patch.object(repo_tokens, "verify_git_token",
                      return_value=(True, "ok")):
        client.put(f"/api/projects/{pid}/repos/backend/token",
                   json={"token": "repo_tok"})
        client.put(f"/api/profiles/{client.admin_id}/git-token",
                   json={"token": "profile_tok"})
    assert core_services.resolve_git_token(pid, "backend",
                                           client.admin_id) == "repo_tok"
    # No repo token → falls back to the profile token.
    client.put(f"/api/projects/{pid}/repos/backend/token", json={"token": ""})
    assert core_services.resolve_git_token(pid, "backend",
                                           client.admin_id) == "profile_tok"
