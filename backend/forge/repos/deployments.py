"""Data access for deploy target settings.

Services compose; repos own the SQL (CLAUDE.md). Generic on purpose — the
deploy target is stored as JSON on the Project (`kind` picks the deploy
adapter, `config_json` is an opaque per-kind blob), and cloud-provider
credentials live one row per (org, kind) in `deploy_credentials`. No provider
name appears here beyond the `kind` discriminator; adding a provider is a new
adapter class, never new columns.
"""

from __future__ import annotations

import json

from backend import secret_box
from backend.models import Deployment, DeployCredential, Project, ProjectRepo

# Frontend-facing status pills (frontend/docs/deploy-backend-requirements.md §1).
ACTIVE_STATUSES = ("queued", "building")


# ── Project deploy target ────────────────────────────────────────────────

def get_target(db, project_id: str) -> dict | None:
    """The project's deploy target as {kind, config}, or None if the project
    doesn't exist. config is the parsed opaque blob ({} when unset)."""
    project = db.get(Project, project_id)
    if project is None:
        return None
    raw = project.deploy_target_config_json
    return {
        "kind": project.deploy_target_kind or "railway",
        "config": json.loads(raw) if raw else {},
    }


def set_target(db, project_id: str, *, kind: str, config: dict) -> dict:
    """Set the project's deploy target. Caller owns the commit. Raises
    ValueError if the project doesn't exist."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project not found: {project_id}")
    project.deploy_target_kind = kind
    project.deploy_target_config_json = json.dumps(config) if config else None
    db.flush()
    return {"kind": project.deploy_target_kind, "config": config}


# ── Cloud-provider credentials (one per org + provider kind) ──────────────

def get_credential(db, org_id: str, kind: str) -> str | None:
    """The org's stored token for provider `kind` (decrypted). Server-side use
    only — never serialize this back to a client. Stored encrypted at rest
    (AP-533); legacy plaintext rows decrypt to themselves."""
    row = (db.query(DeployCredential)
             .filter(DeployCredential.org_id == org_id,
                     DeployCredential.kind == kind)
             .first())
    return secret_box.decrypt(row.token) if row else None


def get_credential_status(db, org_id: str, kind: str) -> dict:
    """Non-secret view of one provider credential: whether a token is set and
    its cached validity. Never includes the token value."""
    row = (db.query(DeployCredential)
             .filter(DeployCredential.org_id == org_id,
                     DeployCredential.kind == kind)
             .first())
    if row is None:
        return {"kind": kind, "has_token": False, "valid": None, "checked_at": None}
    return {
        "kind": kind,
        "has_token": bool(row.token),
        "valid": row.token_valid,
        "checked_at": (row.token_checked_at.isoformat()
                       if row.token_checked_at else None),
    }


def list_credential_statuses(db, org_id: str) -> list[dict]:
    """Non-secret status of every provider credential the org has stored."""
    rows = (db.query(DeployCredential)
              .filter(DeployCredential.org_id == org_id)
              .all())
    return [
        {
            "kind": r.kind,
            "has_token": bool(r.token),
            "valid": r.token_valid,
            "checked_at": (r.token_checked_at.isoformat()
                           if r.token_checked_at else None),
        }
        for r in rows
    ]


def set_credential(db, org_id: str, kind: str, *, token: str | None,
                   valid: bool | None, checked_at) -> None:
    """Upsert the org's token + cached validity for provider `kind`. Caller
    owns the commit. token=None clears the stored value (row kept for its
    cached status). Generic — no provider-specific branching."""
    row = (db.query(DeployCredential)
             .filter(DeployCredential.org_id == org_id,
                     DeployCredential.kind == kind)
             .first())
    if row is None:
        row = DeployCredential(org_id=org_id, kind=kind)
        db.add(row)
    row.token = secret_box.encrypt(token)
    row.token_valid = valid
    row.token_checked_at = checked_at
    db.flush()


# ── Deployments (one row per build of a project branch) ───────────────────

def create_deployment(db, *, org_id: str, project_id: str, branch: str,
                      is_main: bool, provider_kind: str, trigger: str,
                      status: str, status_reason: str,
                      provider_deployment_id: str | None = None,
                      url: str | None = None, step: int | None = None,
                      total_steps: int | None = None,
                      commit_sha: str | None = None,
                      commit_message: str | None = None,
                      author: str | None = None,
                      author_is_agent: bool = False) -> Deployment:
    """Insert a new deployment row. Caller owns the commit."""
    row = Deployment(
        org_id=org_id, project_id=project_id, branch=branch, is_main=is_main,
        provider_kind=provider_kind, trigger=trigger, status=status,
        status_reason=status_reason, provider_deployment_id=provider_deployment_id,
        url=url, step=step, total_steps=total_steps, commit_sha=commit_sha,
        commit_message=commit_message, author=author, author_is_agent=author_is_agent)
    db.add(row)
    db.flush()
    return row


def get_deployment(db, deployment_id: str) -> Deployment | None:
    return db.get(Deployment, deployment_id)


def get_deployment_by_provider_id(db, provider_deployment_id: str) -> Deployment | None:
    """Newest deployment carrying this adapter handle (a redeploy reuses it)."""
    if not provider_deployment_id:
        return None
    return (db.query(Deployment)
              .filter(Deployment.provider_deployment_id == provider_deployment_id)
              .order_by(Deployment.updated_at.desc())
              .first())


def online_runtime_id(db) -> str | None:
    """A connected daemon runtime in the current org (freshest heartbeat
    first) — where a provider that runs on the user's machine gets sent."""
    from backend.forge.models import ForgeRuntime, RuntimeStatus
    row = (db.query(ForgeRuntime)
             .filter(ForgeRuntime.status.in_((RuntimeStatus.ONLINE, RuntimeStatus.BUSY)))
             .order_by(ForgeRuntime.last_heartbeat.desc().nulls_last())
             .first())
    return row.id if row else None


def list_deployments(db, project_id: str) -> list[Deployment]:
    """Every deployment for a project, newest first."""
    return (db.query(Deployment)
              .filter(Deployment.project_id == project_id)
              .order_by(Deployment.updated_at.desc())
              .all())


def latest_deployment_per_branch(db, project_id: str) -> dict[str, Deployment]:
    """Most-recent deployment for each branch of a project (branch -> row)."""
    latest: dict[str, Deployment] = {}
    for row in list_deployments(db, project_id):  # newest first
        latest.setdefault(row.branch, row)
    return latest


def active_deployment_for_branch(db, project_id: str, branch: str) -> Deployment | None:
    """An in-flight (queued/building) deployment for this branch, if any —
    the idempotency key for `POST /deployments`."""
    return (db.query(Deployment)
              .filter(Deployment.project_id == project_id,
                      Deployment.branch == branch,
                      Deployment.status.in_(ACTIVE_STATUSES))
              .order_by(Deployment.updated_at.desc())
              .first())


def update_deployment(db, deployment_id: str, **fields) -> Deployment | None:
    """Patch mutable fields on a deployment. Caller owns the commit."""
    row = db.get(Deployment, deployment_id)
    if row is None:
        return None
    for key, value in fields.items():
        setattr(row, key, value)
    db.flush()
    return row


def github_token_for_project(db, project_id: str) -> str | None:
    """The git access token the deploy flow should use to talk to GitHub for
    this project — the primary repo's token (AP-302). None if unset."""
    row = (db.query(ProjectRepo)
             .filter(ProjectRepo.project_id == project_id,
                     ProjectRepo.is_primary == True)  # noqa: E712
             .first())
    if row is None:
        row = (db.query(ProjectRepo)
                 .filter(ProjectRepo.project_id == project_id)
                 .first())
    return row.access_token if row else None


def delete_deployments_for_project(db, project_id: str) -> int:
    """Remove all deployment rows for a project (disconnect teardown).
    Caller owns the commit. Returns the number deleted."""
    n = (db.query(Deployment)
           .filter(Deployment.project_id == project_id)
           .delete(synchronize_session=False))
    return n
