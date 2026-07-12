"""Public CLI release endpoints — Railway-hosted daemon install/update."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.rest_api import app


@pytest.fixture
def cli_static(tmp_path, monkeypatch):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    wheel = wheels / "agentira_cli-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"fake-wheel")
    manifest = {
        "version": "9.9.9",
        "min_python": "3.11",
        "wheel_filename": wheel.name,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("AGENTIRA_CLI_STATIC_DIR", str(tmp_path))
    return tmp_path


def test_cli_release_returns_install_url(cli_static):
    client = TestClient(app)
    resp = client.get(
        "/api/public/cli-release",
        headers={"Host": "agentira.example.com", "X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "9.9.9"
    assert data["min_python"] == "3.11"
    assert data["install_url"] == (
        "https://agentira.example.com/api/public/cli/wheels/agentira_cli-9.9.9-py3-none-any.whl"
    )
    assert data["install_sh_url"] == "https://agentira.example.com/api/public/install.sh"


def test_cli_wheel_download(cli_static):
    client = TestClient(app)
    resp = client.get("/api/public/cli/wheels/agentira_cli-9.9.9-py3-none-any.whl")
    assert resp.status_code == 200
    assert resp.content == b"fake-wheel"
    assert "application/octet-stream" in resp.headers.get("content-type", "")


def test_cli_wheel_rejects_path_traversal(cli_static):
    client = TestClient(app)
    assert client.get("/api/public/cli/wheels/../manifest.json").status_code == 404


def test_cli_release_404_when_no_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIRA_CLI_STATIC_DIR", str(tmp_path / "missing"))
    client = TestClient(app)
    assert client.get("/api/public/cli-release").status_code == 404


def test_install_sh_is_served(cli_static):
    client = TestClient(app)
    resp = client.get("/api/public/install.sh")
    assert resp.status_code == 200
    assert "agentira-cli" in resp.text.lower() or "agentira" in resp.text.lower()