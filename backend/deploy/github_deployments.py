"""AP-316: GitHub Deployments API — the shared ledger every deploy, by
anyone, lands on when a repo is linked (ADR-011 §4).

Stdlib urllib only, same shape as `backend/repo_tokens.py`. Skips cleanly
(returns None, does nothing) when there's no repo/token to record against —
phase-1 `docker` deploys with no PR yet are the common case (ADR-011 §4).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from backend.repo_tokens import parse_github_repo

_API = "https://api.github.com"


def record_deployment(
    repo_url: str | None,
    token: str | None,
    ref: str,
    environment: str,
    description: str = "",
    timeout: float = 8.0,
) -> int | None:
    """POST /repos/{owner}/{repo}/deployments. Returns the deployment id,
    or None if repo linkage is missing (no repo_url/token) or the call
    fails — callers must not treat this as fatal (ADR-011 §4)."""
    parsed = parse_github_repo(repo_url)
    if not parsed or not token:
        return None
    owner, repo = parsed
    body = json.dumps({
        "ref": ref,
        "environment": environment,
        "description": description,
        "auto_merge": False,
        "required_contexts": [],
    }).encode()
    req = urllib.request.Request(
        f"{_API}/repos/{owner}/{repo}/deployments",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["id"]
    except (urllib.error.URLError, KeyError, ValueError):
        return None


def record_deployment_status(
    repo_url: str | None,
    token: str | None,
    deployment_id: int,
    state: str,
    deployment_url: str | None = None,
    timeout: float = 8.0,
) -> bool:
    """POST /repos/{owner}/{repo}/deployments/{id}/statuses. `state` is a
    GitHub Deployments state (e.g. "in_progress", "success", "failure").
    Returns False (never raises) on missing linkage or a failed call."""
    parsed = parse_github_repo(repo_url)
    if not parsed or not token:
        return False
    owner, repo = parsed
    payload: dict = {"state": state}
    if deployment_url:
        payload["environment_url"] = deployment_url
    req = urllib.request.Request(
        f"{_API}/repos/{owner}/{repo}/deployments/{deployment_id}/statuses",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.URLError:
        return False
