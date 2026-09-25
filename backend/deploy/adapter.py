"""AP-316: `DeployAdapter` — the abstract contract every deploy target kind
implements (ADR-011 §2/§6): one ABC, one subclass per backend,
capability-gated no-ops instead of exceptions for whatever a target can't do.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from backend.deploy.contract import Capability, DeploymentResult, DeploymentStatus, DeployTargetConfig


def unsupported_result(capability: Capability, deployment_id: str = "") -> DeploymentResult:
    """Sentinel result for a capability the adapter doesn't declare."""
    return DeploymentResult(
        deployment_id=deployment_id,
        status=DeploymentStatus.FAILED,
        detail=f"unsupported: {capability.value}",
    )


class DeployAdapter(ABC):
    """Base interface for all deploy targets. One instance per `kind`,
    registered via `backend.deploy.registry.register`.
    """

    #: capabilities this adapter actually implements — subclasses override.
    capabilities: frozenset[Capability] = frozenset()

    #: False for a provider that needs no stored API key (local Docker).
    requires_credential: bool = True

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def verify_credential(self, token: str) -> tuple[bool | None, str]:
        """Probe the provider's API to confirm `token` authenticates. Returns
        (valid, human_readable_detail). Provider-specific — each adapter
        overrides with a single cheap API call (never raises).

        `valid` is `None` for "couldn't check" — the provider was unreachable,
        or something upstream of it refused us. That is not the same as a bad
        token and must never be surfaced as one. Default: verification
        unsupported, so a target kind with no adapter can't falsely report a
        token as valid."""
        return False, "credential verification not supported for this target"

    def prepare(self, db, project, config: dict) -> dict:
        """Fill in target config only the backend knows (project context)
        before `deploy()`. Default: the stored config, unchanged."""
        return config

    @abstractmethod
    def deploy(self, target: DeployTargetConfig, ref: str) -> DeploymentResult:
        """Deploy `ref` (branch/commit) to `target`. Always implemented —
        DEPLOY is the one capability every adapter must declare."""

    @abstractmethod
    def status(self, deployment_id: str) -> DeploymentStatus:
        """Current status of a prior `deploy()` call."""

    @abstractmethod
    def logs(self, deployment_id: str) -> list[str]:
        """Recent log lines. `[]` if unsupported or nothing captured yet."""

    @abstractmethod
    def preview_url(self, deployment_id: str) -> str | None:
        """Clickable URL for the deployment, or `None` if not (yet)
        available / unsupported."""

    @abstractmethod
    def teardown(self, deployment_id: str) -> None:
        """Tear the deployment down. No-op if already gone or unsupported."""
