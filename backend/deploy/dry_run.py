"""AP-316: `DryRunAdapter` — reference adapter used to validate the
contract itself. No process, no network; in-memory state only. AP-317
(docker) and AP-318 (railway) are the real adapters; this one exists so the
conformance suite (and this task's tests) has something to run against.
"""
from __future__ import annotations

import uuid

from backend.deploy.adapter import DeployAdapter
from backend.deploy.contract import Capability, DeploymentResult, DeploymentStatus, DeployTargetConfig


class DryRunAdapter(DeployAdapter):
    capabilities = frozenset({
        Capability.DEPLOY,
        Capability.STATUS,
        Capability.LOGS,
        Capability.PREVIEW_URL,
        Capability.TEARDOWN,
    })

    def __init__(self) -> None:
        self._deployments: dict[str, DeploymentStatus] = {}

    def deploy(self, target: DeployTargetConfig, ref: str) -> DeploymentResult:
        deployment_id = uuid.uuid4().hex[:12]
        self._deployments[deployment_id] = DeploymentStatus.LIVE
        url = f"http://localhost:0/dry-run/{deployment_id}" if target.kind.value == "docker" else None
        return DeploymentResult(
            deployment_id=deployment_id,
            status=DeploymentStatus.LIVE,
            url=url,
            detail=f"dry-run deploy of {ref}",
        )

    def status(self, deployment_id: str) -> DeploymentStatus:
        return self._deployments.get(deployment_id, DeploymentStatus.FAILED)

    def logs(self, deployment_id: str) -> list[str]:
        if deployment_id not in self._deployments:
            return []
        return [f"dry-run: deployment {deployment_id} is {self._deployments[deployment_id].value}"]

    def preview_url(self, deployment_id: str) -> str | None:
        if deployment_id not in self._deployments:
            return None
        return f"http://localhost:0/dry-run/{deployment_id}"

    def teardown(self, deployment_id: str) -> None:
        self._deployments.pop(deployment_id, None)
