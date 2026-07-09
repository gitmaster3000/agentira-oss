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

from backend.models import DeployCredential, Project


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
    """The org's stored token for provider `kind` (raw). Server-side use
    only — never serialize this back to a client."""
    row = (db.query(DeployCredential)
             .filter(DeployCredential.org_id == org_id,
                     DeployCredential.kind == kind)
             .first())
    return row.token if row else None


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
    row.token = token
    row.token_valid = valid
    row.token_checked_at = checked_at
    db.flush()
