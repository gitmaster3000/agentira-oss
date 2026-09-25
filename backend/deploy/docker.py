"""Local Docker deploy provider (`TargetKind.DOCKER`).

The backend runs in a container with no access to the host's Docker, so this
adapter never runs `docker` itself. Every action is a `deploy` frame to the
user's daemon (agentira-cli), the same shape as workflow integration
(`ws_dispatch.dispatch_integrate` → daemon `_integrate`). The daemon clones the
repo at the ref into its own dir, builds/runs it, health-probes it, and POSTs
status + logs back to `/api/forge/daemon/deploy-result`; `DeployFlow.
apply_daemon_result` writes that onto the deployment row.

The provider handle (`provider_deployment_id`) is `<runtime_id>:<key>` — the
runtime routes later teardown/status/logs frames to the same machine, the key
names the deploy on that machine (compose project / container / labels).

`target.config` keys (all optional, never secret):
  source_url     git remote to clone (default: the project's primary repo)
  runtime_id     which connected computer runs it (default: any online one)
  health_path    path probed for a < 400 answer (default "/")
  service        compose service that gets the public port (default: first
                 service that publishes a port)
  container_port port the app listens on inside the container (default:
                 image EXPOSE / compose mapping / 80)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid

from backend.deploy.adapter import DeployAdapter
from backend.deploy.contract import (
    Capability, DeploymentResult, DeploymentStatus, DeployTargetConfig)

_log = logging.getLogger("deploy.docker")

# Git ref shape we accept: no leading dash (option injection), no `..`, no
# whitespace or shell metacharacters. The daemon re-checks — it is the boundary.
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._~/?&=%-]{0,199}$")
_CONFIG_KEYS = ("health_path", "service", "container_port")

# Row status (frontend pill) → contract status.
_FROM_PILL = {
    "queued": DeploymentStatus.PENDING,
    "building": DeploymentStatus.RUNNING,
    "live": DeploymentStatus.LIVE,
    "failed": DeploymentStatus.FAILED,
    "crashed": DeploymentStatus.FAILED,
    "stopped": DeploymentStatus.ROLLED_BACK,
}


def validate_ref(ref: str) -> str:
    ref = (ref or "").strip()
    if not _REF_RE.match(ref) or ".." in ref or ref.endswith((".lock", "/", ".")):
        raise ValueError(f"{ref!r} is not a branch name we can deploy")
    return ref


def deploy_key(project_id: str, branch: str) -> str:
    """Stable, docker-safe name for one (project, branch). The hash keeps two
    branches that slug the same (`feat/a`, `feat-a`) apart."""
    slug = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")[:40] or "branch"
    digest = hashlib.sha256(f"{project_id}\0{branch}".encode()).hexdigest()[:10]
    return f"agentira-{slug}-{digest}"


def _send(runtime_id: str, payload: dict) -> bool:
    """The daemon seam. Hands the frame to the WS hub (durable via the
    dispatch outbox); tests replace this."""
    from backend.forge.services import _dispatch_coro
    from backend.forge.ws_dispatch import hub
    _dispatch_coro(hub.dispatch_deploy(runtime_id=runtime_id, payload=payload))
    return True


def _split(handle: str) -> tuple[str, str]:
    runtime_id, _, key = (handle or "").partition(":")
    return runtime_id, key


def _frame(action: str, handle: str, **extra) -> dict:
    return {"type": "deploy", "event_id": f"deploy-{uuid.uuid4()}",
            "action": action, "deployment_id": handle, **extra}


def _last_report(handle: str):
    from backend.db import SessionLocal
    from backend.forge.repos import deployments as deploy_repo
    with SessionLocal() as db:
        row = deploy_repo.get_deployment_by_provider_id(db, handle)
        if row is None:
            return None, [], None
        logs = [line.get("text", "") for line in json.loads(row.logs_json or "[]")]
        return row.status, logs, row.url


class DockerAdapter(DeployAdapter):
    """Local Docker on the user's own computer, driven through the daemon."""

    requires_credential = False
    capabilities = frozenset({
        Capability.DEPLOY, Capability.STATUS, Capability.LOGS,
        Capability.PREVIEW_URL, Capability.TEARDOWN,
    })

    def verify_credential(self, token: str) -> tuple[bool | None, str]:
        return True, "local Docker needs no key"

    def prepare(self, db, project, config: dict) -> dict:
        """Resolve what the daemon needs that only the backend knows: which
        computer runs it and where the code lives."""
        from backend.forge.repos import deployments as deploy_repo
        resolved = dict(config)
        resolved["project_id"] = project.id
        if not resolved.get("runtime_id"):
            resolved["runtime_id"] = deploy_repo.online_runtime_id(db) or ""
        if not resolved.get("source_url"):
            from backend import services as core_services
            repo = core_services.resolve_project_repo(project.id, None) or {}
            resolved["source_url"] = repo.get("repo_url") or ""
        return resolved

    def deploy(self, target: DeployTargetConfig, ref: str) -> DeploymentResult:
        cfg = target.config
        branch = validate_ref(cfg.get("branch") or ref)
        ref = validate_ref(ref)
        health_path = cfg.get("health_path") or "/"
        if not _PATH_RE.match(health_path):
            raise ValueError(f"health check path {health_path!r} must start with /")
        project_id = cfg.get("project_id") or target.name or "default"
        runtime_id = cfg.get("runtime_id") or ""
        source_url = cfg.get("source_url") or target.repo_url or ""
        key = deploy_key(project_id, branch)
        if not runtime_id:
            return DeploymentResult(
                deployment_id="", status=DeploymentStatus.FAILED,
                detail="No computer is connected to run this deploy — start the "
                       "Agentira app on the machine that has Docker.")
        if not source_url:
            return DeploymentResult(
                deployment_id="", status=DeploymentStatus.FAILED,
                detail="This project has no code repository linked, so there is "
                       "nothing to deploy.")
        handle = f"{runtime_id}:{key}"
        _send(runtime_id, _frame(
            "deploy", handle, project_id=project_id, branch=branch, ref=ref,
            source_url=source_url,
            config={k: cfg[k] for k in _CONFIG_KEYS if cfg.get(k)} | {
                "health_path": health_path}))
        _log.info("docker deploy requested: project=%s branch=%s runtime=%s",
                  project_id, branch, runtime_id)
        return DeploymentResult(
            deployment_id=handle, status=DeploymentStatus.PENDING,
            detail="Queued — waiting for your computer to build it.")

    def status(self, deployment_id: str) -> DeploymentStatus:
        """Last status the daemon reported; also asks it for a fresh one."""
        self._refresh("status", deployment_id)
        pill, _logs, _url = _last_report(deployment_id)
        return _FROM_PILL.get(pill, DeploymentStatus.FAILED)

    def logs(self, deployment_id: str) -> list[str]:
        """Last log lines the daemon reported; also asks it for fresh ones."""
        self._refresh("logs", deployment_id)
        return _last_report(deployment_id)[1]

    def preview_url(self, deployment_id: str) -> str | None:
        return _last_report(deployment_id)[2]

    def teardown(self, deployment_id: str) -> None:
        self._refresh("teardown", deployment_id)

    @staticmethod
    def _refresh(action: str, handle: str) -> None:
        runtime_id, key = _split(handle)
        if runtime_id and key:
            _send(runtime_id, _frame(action, handle))
