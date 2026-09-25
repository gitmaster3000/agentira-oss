"""AP-451: the deploy *flow* — connect a provider, then create, track and tear
down deployments of a project's branches.

Target + credential settings live in `DeploymentManager`; this handler owns the
deployment lifecycle. Both are provider-agnostic: a target `kind` selects a
`DeployAdapter` from the registry and every provider call goes through it, so
adding a provider is a new adapter class, not a change here.

`services.py` is the gateway — it owns the session and the commit and funnels
REST/MCP calls in. This handler takes an open session and never commits.

The shapes produced here (DeployConnection, BranchEntry, Deployment, the logs
page) are the frontend contract in
`frontend/docs/deploy-backend-requirements.md`.

Honest scope notes (this build):
  * Branch enumeration lists the repo's real branches from GitHub (via the
    project's repo token) merged with per-branch deployment state; it falls
    back to deployment-derived branches when GitHub is unlinked/unreachable.
    Per-branch commit metadata (sha/message/author) still comes from
    deployment rows — full commit enrichment is a follow-up.
  * `repo_access` really probes the GitHub repo with the project's token and
    reports access honestly in plain language.
  * The Railway *live* deploy path is wired through the adapter but exercising it
    end-to-end needs a real Railway token + project linkage (see
    `deploy/railway.py`); it is untested against a live account here.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os

from backend import repo_tokens
from backend.deploy import github_deployments, registry
from backend.deploy.contract import (
    DeploymentStatus, DeployTargetConfig, TargetKind)
from backend.deploy.railway import TOKEN_ENV_VARS
from backend.forge.repos import deployments as deploy_repo
from backend.models import Project

_log = logging.getLogger("deploy.flow")

# contract DeploymentStatus -> the six frontend pills (§1).
_STATUS = {
    DeploymentStatus.PENDING: "queued",
    DeploymentStatus.RUNNING: "building",
    DeploymentStatus.LIVE: "live",
    DeploymentStatus.FAILED: "failed",
    DeploymentStatus.ROLLED_BACK: "stopped",
}

# The backend should always beat the frontend's generic fallback (§4): every
# status carries a plain-language reason, never an empty string.
_REASON = {
    "queued": "Queued — waiting for a build slot.",
    "building": "Building — installing dependencies and compiling.",
    "live": "Deployed and healthy.",
    "failed": "Build failed — open the logs for the error.",
    "crashed": "App crashed after deploy — see runtime logs.",
    "stopped": "Preview stopped — redeploy to bring it back.",
}

# Frontend status pill -> GitHub Deployments state (ADR-011 §4).
_GH_STATE = {
    "queued": "queued",
    "building": "in_progress",
    "live": "success",
    "failed": "failure",
    "crashed": "failure",
    "stopped": "inactive",
}

_INSTALL_URL = "https://github.com/apps/railway/installations/new"


class DeployFlow:
    """Owns a project's deployment lifecycle. Methods take an open session; the
    caller (services) owns the transaction and commits."""

    # ── provider connection ──────────────────────────────────────────────

    def get_connection(self, db, project_id: str) -> dict:
        """The project's DeployConnection, or `{"connected": false}` when no
        provider is attached. The API key is never included."""
        project = self._require_project(db, project_id)
        target = deploy_repo.get_target(db, project_id)
        config = target["config"]
        cred = deploy_repo.get_credential_status(db, project.org_id, target["kind"])
        connected = bool(cred["has_token"] and config.get("repo")
                         and config.get("service_id"))
        if not connected:
            return {"connected": False}
        return {
            "connected": True,
            "provider": target["kind"],
            "repo": config.get("repo", ""),
            "service_name": config.get("service_name", ""),
            "service_region": config.get("service_region"),
            "key_valid": bool(cred["valid"]),
            "key_checked_at": cred["checked_at"],
            "connected_at": config.get("connected_at"),
        }

    def connect(self, db, project_id: str, *, provider: str, api_key: str,
                repo: str, service_id: str) -> dict:
        """Attach a provider: probe the key, store the credential + target, and
        kick the first deploy of `main`. Returns the DeployConnection."""
        project = self._require_project(db, project_id)
        kind = self._valid_kind(provider)
        repo = (repo or "").strip()
        service_id = (service_id or "").strip()
        if not repo or not service_id:
            raise ValueError("repo and service_id are required to connect")

        adapter = self._adapter(kind)
        probe = getattr(adapter, "probe_key", None)
        if probe is None:
            raise ValueError(f"{kind} does not support connecting yet")
        result = probe((api_key or "").strip())
        if not result.get("valid"):
            err = result.get("error") or {}
            raise ValueError(err.get("headline") or "provider rejected this key")

        svc = next((s for s in result.get("services", [])
                    if s.get("id") == service_id), None)
        config = {
            "repo": repo,
            "service_id": service_id,
            "service_name": (svc or {}).get("name", service_id),
            "service_region": (svc or {}).get("region"),
            "service": (svc or {}).get("name", service_id),
            "connected_at": _utcnow().isoformat(),
        }
        deploy_repo.set_credential(
            db, project.org_id, kind,
            token=(api_key or "").strip(), valid=True, checked_at=_utcnow())
        deploy_repo.set_target(db, project_id, kind=kind, config=config)
        _log.info("deploy provider connected: project=%s kind=%s repo=%s",
                  project_id, kind, repo)

        try:
            self._deploy_branch(db, project, kind, config,
                                branch="main", trigger="push")
        except Exception as exc:
            # A failed first deploy must never vanish (§4): record it as a
            # `failed` row so the Deploy tab shows what went wrong.
            _log.warning("first deploy of main failed: project=%s kind=%s: %s",
                         project_id, kind, exc)
            deploy_repo.create_deployment(
                db, org_id=project.org_id, project_id=project.id, branch="main",
                is_main=True, provider_kind=kind, trigger="push", status="failed",
                status_reason=(
                    "First deploy couldn't start — "
                    f"{exc}. Fix the issue, then redeploy."))
        return self.get_connection(db, project_id)

    def reverify(self, db, project_id: str) -> dict:
        """Re-probe the stored key and refresh its cached validity."""
        project = self._require_project(db, project_id)
        target = deploy_repo.get_target(db, project_id)
        kind = target["kind"]
        token = deploy_repo.get_credential(db, project.org_id, kind)
        if not token:
            raise ValueError("no stored key to re-verify")
        valid, _detail = self._adapter(kind).verify_credential(token)
        deploy_repo.set_credential(
            db, project.org_id, kind,
            token=token, valid=valid, checked_at=_utcnow())
        return self.get_connection(db, project_id)

    def disconnect(self, db, project_id: str) -> None:
        """Detach the provider: tear down live previews, drop deployment rows,
        clear the credential and target config."""
        project = self._require_project(db, project_id)
        target = deploy_repo.get_target(db, project_id)
        kind = target["kind"]
        token = deploy_repo.get_credential(db, project.org_id, kind)
        for row in deploy_repo.list_deployments(db, project_id):
            if not row.is_main and row.provider_deployment_id:
                with contextlib.suppress(Exception), _provider_token(kind, token):
                    self._adapter(kind).teardown(row.provider_deployment_id)
        deploy_repo.delete_deployments_for_project(db, project_id)
        deploy_repo.set_credential(
            db, project.org_id, kind, token=None, valid=None, checked_at=None)
        deploy_repo.set_target(db, project_id, kind=kind, config={})
        _log.info("deploy provider disconnected: project=%s", project_id)

    def repo_access(self, db, project_id: str, provider: str) -> dict:
        """Whether we can actually build this project's repo — a real GitHub
        API probe with the project's repo token (AP-533). `reason` is plain
        language for the UI; `install_url` is offered when access is missing so
        the user has somewhere to go."""
        self._require_project(db, project_id)
        self._valid_kind(provider)
        target = deploy_repo.get_target(db, project_id)
        repo = target["config"].get("repo", "")
        token = deploy_repo.github_token_for_project(db, project_id)
        granted, reason = repo_tokens.repo_access(_repo_url(target["config"]), token)
        result = {"repo": repo, "granted": granted, "reason": reason}
        if not granted:
            result["install_url"] = _INSTALL_URL
        return result

    # ── deployments ──────────────────────────────────────────────────────

    def list_deployments(self, db, project_id: str) -> dict:
        """One BranchEntry per branch — `main` first (even if never deployed),
        then the repo's real branches (from GitHub), then any branch that has a
        deployment but no longer exists on the remote. A branch with no
        deployment yet appears with `deployment: null`. If GitHub is unlinked
        or unreachable we fall back to the branches we've deployed."""
        self._require_project(db, project_id)
        latest = deploy_repo.latest_deployment_per_branch(db, project_id)
        target = deploy_repo.get_target(db, project_id)
        token = deploy_repo.github_token_for_project(db, project_id)
        real = repo_tokens.list_repo_branches(_repo_url(target["config"]), token)

        # main first, then real branches (repo order), then deployment-only
        # branches (deployed here but not on the remote), newest first.
        seen = {"main"}
        ordered = ["main"]
        for name in real:
            if name not in seen:
                ordered.append(name)
                seen.add(name)
        leftover = sorted(
            (b for b in latest if b not in seen),
            key=lambda b: latest[b].updated_at, reverse=True)
        ordered.extend(leftover)

        branches = [
            _branch_entry(latest[name]) if name in latest
            else _empty_branch(name, is_main=(name == "main"))
            for name in ordered
        ]
        return {"branches": branches}

    def create_deployment(self, db, project_id: str, *, branch: str,
                          trigger: str | None = None) -> dict:
        """Deploy `branch`. Idempotent: a second call while one is queued or
        building returns the in-flight deployment instead of starting another."""
        project = self._require_project(db, project_id)
        branch = (branch or "").strip()
        if not branch:
            raise ValueError("branch is required")
        target = deploy_repo.get_target(db, project_id)
        kind = target["kind"]
        config = target["config"]
        if not (deploy_repo.get_credential(db, project.org_id, kind)
                and config.get("service_id")):
            raise ValueError("connect a deploy provider first")

        existing = deploy_repo.active_deployment_for_branch(db, project_id, branch)
        if existing:
            return _deployment_dict(existing)

        trigger = trigger or ("manual" if branch == "main" else "preview")
        row = self._deploy_branch(db, project, kind, config,
                                  branch=branch, trigger=trigger)
        return _deployment_dict(row)

    def redeploy(self, db, project_id: str, deployment_id: str) -> dict:
        """Re-run a deployment in place (same row, same branch)."""
        project = self._require_project(db, project_id)
        row = self._require_deployment(db, project_id, deployment_id)
        target = deploy_repo.get_target(db, project_id)
        new = self._deploy_branch(db, project, target["kind"], target["config"],
                                  branch=row.branch, trigger="manual", existing=row)
        return _deployment_dict(new)

    def stop(self, db, project_id: str, deployment_id: str) -> None:
        """Tear a preview down. Rejects `main` (409-worthy) — main is never
        stoppable even though the UI never offers it."""
        project = self._require_project(db, project_id)
        row = self._require_deployment(db, project_id, deployment_id)
        if row.is_main:
            raise PermissionError("main deployments cannot be stopped")
        token = deploy_repo.get_credential(db, project.org_id, row.provider_kind)
        if row.provider_deployment_id:
            with contextlib.suppress(Exception), _provider_token(row.provider_kind, token):
                self._adapter(row.provider_kind).teardown(row.provider_deployment_id)
        deploy_repo.update_deployment(
            db, deployment_id, status="stopped", status_reason=_REASON["stopped"])

    def get_logs(self, db, project_id: str, deployment_id: str,
                 *, cursor: int = 0) -> dict:
        """Cursor-paginated build logs. `cursor` is an opaque line offset the
        client echoes back; only lines after it are returned. `done` is true
        once the deployment has reached a terminal status."""
        project = self._require_project(db, project_id)
        row = self._require_deployment(db, project_id, deployment_id)
        lines: list[dict] = []
        if row.provider_deployment_id:
            token = deploy_repo.get_credential(db, project.org_id, row.provider_kind)
            with contextlib.suppress(Exception), _provider_token(row.provider_kind, token):
                raw = self._adapter(row.provider_kind).logs(row.provider_deployment_id)
                lines = [{"level": _log_level(text), "text": text} for text in raw]
        if not lines and row.logs_json:
            lines = json.loads(row.logs_json)
        cursor = max(0, int(cursor or 0))
        page = lines[cursor:]
        done = row.status in ("live", "failed", "crashed", "stopped")
        return {"lines": page, "next_cursor": cursor + len(page), "done": done}

    # ── internals ────────────────────────────────────────────────────────

    def _deploy_branch(self, db, project: Project, kind: str, config: dict, *,
                       branch: str, trigger: str, existing=None):
        adapter = self._adapter(kind)
        token = deploy_repo.get_credential(db, project.org_id, kind)
        target = DeployTargetConfig(
            kind=TargetKind(kind), name=config.get("service_name", ""),
            config=config, repo_url=_repo_url(config))
        with _provider_token(kind, token):
            result = adapter.deploy(target, branch)
        status = _STATUS.get(result.status, "failed")
        reason = result.detail or _REASON.get(status, "Deployment updated.")
        fields = dict(
            status=status, status_reason=reason,
            provider_deployment_id=result.deployment_id or None,
            url=result.url, trigger=trigger)
        if existing is not None:
            row = deploy_repo.update_deployment(db, existing.id, **fields)
        else:
            row = deploy_repo.create_deployment(
                db, org_id=project.org_id, project_id=project.id, branch=branch,
                is_main=(branch == "main"), provider_kind=kind, **fields)
        self._record_github_deployment(db, project, config, branch, status,
                                        result.url)
        return row

    def _record_github_deployment(self, db, project: Project, config: dict,
                                   branch: str, status: str, url: str | None):
        """Log this deploy on the repo's GitHub Deployments ledger (ADR-011 §4)
        when the repo is on GitHub. No-op / best-effort otherwise — a ledger
        hiccup must never fail the deploy."""
        repo_url = _repo_url(config)
        token = deploy_repo.github_token_for_project(db, project.id)
        if not repo_url or not token:
            return
        try:
            deployment_id = github_deployments.record_deployment(
                repo_url, token, ref=branch, environment="production",
                description=f"Agentira deploy of {branch}")
            if deployment_id is not None:
                github_deployments.record_deployment_status(
                    repo_url, token, deployment_id,
                    state=_GH_STATE.get(status, "in_progress"),
                    deployment_url=url)
        except Exception as exc:  # never fatal
            _log.warning("github deployment ledger failed: project=%s: %s",
                         project.id, exc)

    def _require_project(self, db, project_id: str) -> Project:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        return project

    def _require_deployment(self, db, project_id: str, deployment_id: str):
        row = deploy_repo.get_deployment(db, deployment_id)
        if row is None or row.project_id != project_id:
            raise KeyError(f"deployment {deployment_id} not found")
        return row

    def _valid_kind(self, kind: str) -> str:
        k = (kind or "").strip().lower()
        try:
            return TargetKind(k).value
        except ValueError:
            allowed = ", ".join(t.value for t in TargetKind)
            raise ValueError(f"unknown deploy target kind {kind!r}; allowed: {allowed}")

    def _adapter(self, kind: str):
        try:
            return registry.get_adapter(TargetKind(self._valid_kind(kind)))
        except LookupError:
            raise ValueError(f"{kind} cannot be deployed yet")


# ── module helpers ────────────────────────────────────────────────────────

@contextlib.contextmanager
def _provider_token(kind: str, token: str | None):
    """Expose the stored provider token to the adapter for the duration of one
    call. Railway's adapter reads its token from the environment (ADR-011 §3 —
    never a stored global), so the gateway injects the per-project credential
    here and restores the prior environment afterwards."""
    if not token:
        yield
        return
    saved = {var: os.environ.get(var) for var in TOKEN_ENV_VARS}
    for var in TOKEN_ENV_VARS:
        os.environ[var] = token
    try:
        yield
    finally:
        for var, old in saved.items():
            if old is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = old


def _deployment_dict(row) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "url": row.url,
        "step": row.step,
        "total_steps": row.total_steps,
        "status_reason": row.status_reason or _REASON.get(row.status, "Deployment updated."),
        "trigger": row.trigger,
        "updated_at": row.updated_at.isoformat(),
    }


def _branch_entry(row) -> dict:
    return {
        "branch": row.branch,
        "is_main": row.is_main,
        "commit_sha": row.commit_sha or "",
        "commit_message": row.commit_message or "",
        "author": row.author or "",
        "author_is_agent": row.author_is_agent,
        "committed_at": row.updated_at.isoformat(),
        "deployment": _deployment_dict(row),
    }


def _empty_branch(branch: str, *, is_main: bool) -> dict:
    return {
        "branch": branch,
        "is_main": is_main,
        "commit_sha": "",
        "commit_message": "",
        "author": "",
        "author_is_agent": False,
        "committed_at": None,
        "deployment": None,
    }


def _log_level(text: str) -> str:
    lowered = (text or "").lower()
    if any(hint in lowered for hint in ("error", "failed", "fatal", "exception")):
        return "error"
    if any(hint in lowered for hint in ("warn", "deprecat")):
        return "warn"
    return "info"


def _repo_url(config: dict) -> str | None:
    repo = config.get("repo")
    return f"https://github.com/{repo}.git" if repo else None


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
