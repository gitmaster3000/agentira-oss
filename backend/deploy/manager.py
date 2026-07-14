"""Deployment handler: everything about a project's deploy target and its
cloud-provider credential lives here, behind one class.

`services.py` is the gateway — it owns the DB session and the commit, and
funnels REST/MCP calls in. It hands this manager an open session and delegates;
the manager holds the domain logic (validate the target kind, verify a token
against the provider, read/write through the repo) and its own logger. It never
opens or commits a session itself.

The manager is provider-agnostic: a target `kind` selects a `DeployAdapter`
from the registry, and anything provider-specific (e.g. how a token is
verified) is that adapter's job. Adding a provider is a new adapter class, not
a change here.
"""

from __future__ import annotations

import logging

from backend.deploy import registry
from backend.deploy.contract import TargetKind
from backend.forge.repos import deployments as deploy_repo
from backend.models import Project

_log = logging.getLogger("deploy.manager")


class DeploymentManager:
    """Owns a project's deploy settings. Methods take an open session; the
    caller (services) owns the transaction and commits."""

    def get_settings(self, db, project_id: str) -> dict:
        """The project's deploy target plus the non-secret status of the stored
        credential for that target's provider. Token values are never returned."""
        project = self._require_project(db, project_id)
        target = deploy_repo.get_target(db, project_id)
        credential = deploy_repo.get_credential_status(db, project.org_id, target["kind"])
        return {"target": target, "credential": credential}

    def set_target(self, db, project_id: str, *, kind: str, config: dict | None = None) -> dict:
        """Point the project at a deploy target. `config` is the opaque per-kind
        blob the adapter understands. Returns the same shape as get_settings."""
        project = self._require_project(db, project_id)
        kind = self._valid_kind(kind)
        deploy_repo.set_target(db, project_id, kind=kind, config=config or {})
        _log.info("deploy target set: project=%s kind=%s", project_id, kind)
        target = deploy_repo.get_target(db, project_id)
        credential = deploy_repo.get_credential_status(db, project.org_id, kind)
        return {"target": target, "credential": credential}

    def set_credential(self, db, project_id: str, *, kind: str, token: str) -> dict:
        """Store the org's provider token for `kind` and probe-verify it through
        that provider's adapter. An empty token clears the stored credential.
        Returns the credential's non-secret status plus a human-readable
        `detail`; the token value itself is never returned."""
        project = self._require_project(db, project_id)
        kind = self._valid_kind(kind)
        token = (token or "").strip()

        valid, detail = self._verify_token(kind, token)
        deploy_repo.set_credential(
            db, project.org_id, kind,
            token=token or None, valid=valid,
            checked_at=_utcnow() if token else None)
        _log.info("deploy credential set: org=%s kind=%s valid=%s",
                  project.org_id, kind, valid)

        credential = deploy_repo.get_credential_status(db, project.org_id, kind)
        credential["detail"] = detail
        return credential

    def verify_key(self, db, project_id: str, *, kind: str, token: str) -> dict:
        """Probe a key the user is still typing into the connect wizard. Stores
        nothing. An unusable key comes back as `{"valid": false, "error": …}` —
        a result the wizard renders, not an exception."""
        self._require_project(db, project_id)
        kind = self._valid_kind(kind)
        token = (token or "").strip()
        if not token:
            raise ValueError("api_key is required")

        try:
            adapter = registry.get_adapter(TargetKind(kind))
        except LookupError:
            raise ValueError(f"{kind} cannot be connected yet")
        probe = getattr(adapter, "probe_key", None)
        if probe is None:
            raise ValueError(f"{kind} does not support key verification")

        result = probe(token)
        _log.info("deploy key probed: project=%s kind=%s valid=%s",
                  project_id, kind, result.get("valid"))
        return result

    # ── internals ────────────────────────────────────────────────────────

    def _require_project(self, db, project_id: str) -> Project:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        return project

    def _valid_kind(self, kind: str) -> str:
        """Normalize and validate a target kind. Raises ValueError on an unknown
        kind so junk can't be persisted."""
        k = (kind or "").strip().lower()
        try:
            return TargetKind(k).value
        except ValueError:
            allowed = ", ".join(t.value for t in TargetKind)
            raise ValueError(f"unknown deploy target kind {kind!r}; allowed: {allowed}")

    def _verify_token(self, kind: str, token: str) -> tuple[bool | None, str]:
        """Ask the provider's adapter whether `token` authenticates. Returns
        (valid, detail); valid is None when we can't verify — an empty token, or
        no adapter registered for this provider — so an unverifiable token is
        never reported as valid."""
        if not token:
            return None, "cleared"
        try:
            adapter = registry.get_adapter(TargetKind(kind))
        except LookupError:
            return None, "no adapter for this provider yet"
        return adapter.verify_credential(token)


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
