"""AP-316: deploy adapter contract tests. Pure unit tests — no DB, no
network (GitHub calls are mocked)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from backend.deploy import Capability, DeployTargetConfig, get_adapter, register
from backend.deploy.conformance import run_conformance_suite
from backend.deploy.contract import DeploymentStatus, TargetKind
from backend.deploy.dry_run import DryRunAdapter
from backend.deploy.github_deployments import record_deployment, record_deployment_status


# ── contract / capability model ─────────────────────────────────────────

def test_docker_target_must_be_test_environment():
    DeployTargetConfig(kind=TargetKind.DOCKER, environment="test")
    with pytest.raises(ValidationError):
        DeployTargetConfig(kind=TargetKind.DOCKER, environment="prod")


def test_railway_target_allows_prod():
    cfg = DeployTargetConfig(kind=TargetKind.RAILWAY, environment="prod")
    assert cfg.environment.value == "prod"


def test_unsupported_capability_is_a_no_op_not_an_exception():
    from backend.deploy.adapter import unsupported_result

    result = unsupported_result(Capability.ROLLBACK, deployment_id="abc123")
    assert result.status == DeploymentStatus.FAILED
    assert "rollback" in result.detail


# ── registry ─────────────────────────────────────────────────────────────

def test_registry_round_trip():
    adapter = DryRunAdapter()
    register(TargetKind.DOCKER, adapter)
    assert get_adapter(TargetKind.DOCKER) is adapter


def test_registry_missing_kind_raises():
    with pytest.raises(LookupError):
        get_adapter(TargetKind.K8S)


# ── conformance: deploy -> status transitions -> teardown ───────────────

def test_dry_run_adapter_passes_conformance_suite():
    adapter = DryRunAdapter()
    target = DeployTargetConfig(kind=TargetKind.DOCKER, environment="test")
    run_conformance_suite(adapter, target, ref="main")


def test_dry_run_adapter_deploy_status_teardown_lifecycle():
    adapter = DryRunAdapter()
    target = DeployTargetConfig(kind=TargetKind.DOCKER, environment="test")

    result = adapter.deploy(target, "feature-branch")
    assert result.status == DeploymentStatus.LIVE
    assert adapter.status(result.deployment_id) == DeploymentStatus.LIVE
    assert adapter.preview_url(result.deployment_id) is not None

    adapter.teardown(result.deployment_id)
    assert adapter.status(result.deployment_id) == DeploymentStatus.FAILED
    assert adapter.preview_url(result.deployment_id) is None


# ── GitHub Deployments linkage ───────────────────────────────────────────

def test_record_deployment_skips_cleanly_without_repo_linkage():
    assert record_deployment(None, "token", "main", "test") is None
    assert record_deployment("https://github.com/acme/widgets", None, "main", "test") is None
    assert record_deployment_status(None, "token", 1, "success") is False


def test_record_deployment_written_when_repo_linked():
    fake_response = _FakeUrlopen({"id": 42})
    with patch("backend.deploy.github_deployments.urllib.request.urlopen", return_value=fake_response):
        deployment_id = record_deployment(
            "https://github.com/acme/widgets", "ghp_token", "main", "test", "preview"
        )
    assert deployment_id == 42


def test_record_deployment_status_written_when_repo_linked():
    fake_response = _FakeUrlopen({})
    with patch("backend.deploy.github_deployments.urllib.request.urlopen", return_value=fake_response):
        ok = record_deployment_status(
            "https://github.com/acme/widgets", "ghp_token", 42, "success", "http://localhost:8000"
        )
    assert ok is True


class _FakeUrlopen:
    """Minimal context-manager stand-in for `urllib.request.urlopen`."""

    def __init__(self, payload: dict):
        import json
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body
