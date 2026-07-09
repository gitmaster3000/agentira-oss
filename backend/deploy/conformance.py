"""AP-316: conformance suite every `DeployAdapter` must pass.

Not a pytest file itself — `run_conformance_suite(adapter, target)` is
called from a test (see `backend/tests/test_deploy_contract.py`) and from
AP-317/AP-318's own test suites once those adapters exist.
"""
from __future__ import annotations

from backend.deploy.adapter import DeployAdapter
from backend.deploy.contract import Capability, DeploymentStatus, DeployTargetConfig


def run_conformance_suite(adapter: DeployAdapter, target: DeployTargetConfig, ref: str = "main") -> None:
    """Deploy -> status transitions -> teardown. Raises AssertionError on
    the first violation."""
    assert adapter.supports(Capability.DEPLOY), "every adapter must support DEPLOY"

    result = adapter.deploy(target, ref)
    assert result.deployment_id, "deploy() must return a deployment_id"
    assert result.status in DeploymentStatus, "deploy() must return a known status"

    if adapter.supports(Capability.STATUS):
        status = adapter.status(result.deployment_id)
        assert status == result.status, "status() must reflect the just-created deployment"

    if adapter.supports(Capability.LOGS):
        logs = adapter.logs(result.deployment_id)
        assert isinstance(logs, list), "logs() must return a list"

    if adapter.supports(Capability.PREVIEW_URL):
        adapter.preview_url(result.deployment_id)  # None is a valid answer

    if adapter.supports(Capability.TEARDOWN):
        adapter.teardown(result.deployment_id)
        status_after = adapter.status(result.deployment_id) if adapter.supports(Capability.STATUS) else None
        assert status_after != DeploymentStatus.LIVE, "teardown() must leave the deployment non-live"
