"""AP-316: typed contract shared by every deploy adapter.

Kept decoupled from any DB model on purpose — the `DeployTarget` table and
`Task.deploy_*` columns are AP-314/AP-315's job, not this one's. Callers
(services, tests, future repo-layer code) build a `DeployTargetConfig` from
whatever storage AP-314 lands and hand it to a registered adapter.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Capability(str, Enum):
    """One flag per `DeployAdapter` method. An adapter that doesn't declare
    a capability must still implement the method, returning an
    "unsupported" result rather than raising (ADR-011 §2)."""

    DEPLOY = "deploy"
    STATUS = "status"
    LOGS = "logs"
    PREVIEW_URL = "preview_url"
    ROLLBACK = "rollback"
    TEARDOWN = "teardown"


class TargetKind(str, Enum):
    """ADR-011 §2 taxonomy. gcp_cloud_run/k8s are deferred — no adapter
    registers for them yet, but the kind exists so config validates."""

    DOCKER = "docker"
    RAILWAY = "railway"
    GCP_CLOUD_RUN = "gcp_cloud_run"
    K8S = "k8s"


class Environment(str, Enum):
    TEST = "test"
    PROD = "prod"


class DeploymentStatus(str, Enum):
    """Mirrors the `Task.deploy_status` values sketched in ADR-011 §6."""

    PENDING = "pending"
    RUNNING = "running"
    LIVE = "live"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DeployTargetConfig(BaseModel):
    """Validated, adapter-agnostic view of a deploy target. `config` is an
    opaque per-kind blob (compose file path, Railway project/env id, ...) —
    ADR-011 §6 keeps it untyped so a new `kind` is a new adapter class, not
    a schema migration.

    `docker` only ever runs in `test` — there's no daemon-local "prod".
    """

    kind: TargetKind
    environment: Environment = Environment.TEST
    name: str = ""
    config: dict = Field(default_factory=dict)
    repo_url: str | None = None  # for GitHub Deployments linkage, if any

    @field_validator("environment")
    @classmethod
    def _docker_is_test_only(cls, v: Environment, info) -> Environment:
        kind = info.data.get("kind")
        if kind == TargetKind.DOCKER and v != Environment.TEST:
            raise ValueError("docker targets only support the test environment")
        return v


class DeploymentResult(BaseModel):
    """Return value of `DeployAdapter.deploy()`. Never carries a secret —
    adapters return `{handle, url}`, never the credential used (ADR-011 §3)."""

    deployment_id: str
    status: DeploymentStatus
    url: str | None = None
    detail: str = ""
