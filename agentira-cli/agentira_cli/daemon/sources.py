"""AP-197: daemon-owned source clones for git workspaces.

For a git workspace the daemon clones the project's remote into
``~/.agentira/sources/<slug>/`` and branches per-task worktrees off that clone,
so it never reaches into the user's protected folders. macOS TCC blocks a
background daemon from reading ``~/Desktop`` / ``~/Documents`` / ``~/Downloads``;
cloning the remote over the network sidesteps that entirely.

The clone is cached: cloned once, then ``git fetch --prune`` on later runs.
Clones are serialized per-destination so two concurrent dispatches on the same
repo don't race.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading

from agentira_cli.state.paths import SOURCES_DIR, ensure_home

logger = logging.getLogger("agentira.daemon.sources")

# Folders macOS TCC commonly blocks for a background daemon.
_PROTECTED = ("/Desktop/", "/Documents/", "/Downloads/")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class SourceProvisionError(Exception):
    """A git workspace clone/fetch could not be provisioned."""


def _slug(url: str) -> str:
    """Stable, filesystem-safe directory name for a remote URL.

    Strips the scheme, any ``user@`` / credentials, and a trailing ``.git``,
    then flattens host/path. Two projects on the same remote share one clone
    (their per-task worktrees keep the work independent).
    """
    s = url.strip()
    s = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", s)   # drop scheme
    s = re.sub(r"^[^@/]+@", "", s)                        # drop user@ / creds
    s = s.replace(":", "/")                               # scp-style host:path
    s = re.sub(r"\.git/?$", "", s)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return s or "repo"


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lk = _locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _locks[key] = lk
        return lk


def _git_env() -> dict:
    """Non-interactive git env so a missing credential can never hang the
    daemon waiting on a terminal prompt."""
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def ensure_source_clone(url: str, *, timeout: int = 600) -> tuple[str, str]:
    """Return ``(clone_path, reason)`` for a git workspace URL.

    Clones the remote into ``SOURCES_DIR/<slug>`` on first use; on later use
    runs ``git fetch --prune`` (best-effort — a fetch failure is non-fatal, we
    can still worktree off the cached state). Serialized per destination.

    ``reason`` is ``"cloned"`` on a fresh clone, ``"ok"`` on cache reuse.
    Raises :class:`SourceProvisionError` on a hard clone failure so the caller
    can fail the run fast with a clear cause.
    """
    if not url or not url.strip():
        raise SourceProvisionError("empty git workspace URL")
    ensure_home()
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOURCES_DIR / _slug(url)
    with _lock_for(str(dest)):
        if dest.exists() and _is_bare(dest):
            # Bare master copy already present — just refresh remote-tracking
            # refs so origin/<base> is current for the per-task worktrees.
            r = subprocess.run(
                ["git", "-C", str(dest), "fetch", "--prune", "--quiet", "origin"],
                capture_output=True, text=True, timeout=timeout, env=_git_env(),
            )
            if r.returncode != 0:
                logger.warning("git fetch failed for %s: %s",
                               dest, (r.stderr or r.stdout).strip())
            return str(dest), "ok"
        if dest.exists():
            # A legacy NON-bare clone (or a parked one an agent committed into).
            # Re-clone it bare so nothing can ever sit in / mutate the master.
            # Per-task worktrees are unaffected — their `.git` files point at
            # this source and get re-created on next dispatch.
            logger.info("re-cloning non-bare source %s as bare", dest)
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["git", "clone", "--bare", "--quiet", url, str(dest)],
            capture_output=True, text=True, timeout=timeout, env=_git_env(),
        )
        if r.returncode != 0:
            # Clean up a partial clone so the next attempt starts fresh.
            shutil.rmtree(dest, ignore_errors=True)
            raise SourceProvisionError(
                f"git clone failed for {url}: {(r.stderr or r.stdout).strip()}"
            )
        # A bare clone stores remote branches in refs/heads with no fetch
        # refspec for remote-tracking. Set one + fetch so origin/<base>
        # resolves (the worktree code branches/rebases off origin/<base>).
        subprocess.run(
            ["git", "-C", str(dest), "config", "remote.origin.fetch",
             "+refs/heads/*:refs/remotes/origin/*"],
            capture_output=True, text=True, timeout=timeout, env=_git_env(),
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--prune", "--quiet", "origin"],
            capture_output=True, text=True, timeout=timeout, env=_git_env(),
            check=False,
        )
        return str(dest), "cloned"


def _is_bare(dest) -> bool:
    """True if `dest` is a bare git repo (the protected master copy)."""
    r = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "--is-bare-repository"],
        capture_output=True, text=True, timeout=30, env=_git_env(), check=False,
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def classify_provision_error(exc: Exception, *, source: str = "") -> str:
    """Map a raw provisioning error to a human, actionable cause (AP-196)."""
    msg = str(exc)
    low = msg.lower()
    protected = any(seg in (source or "") for seg in _PROTECTED)
    if ("operation not permitted" in low
            or "unable to read current working directory" in low
            or (protected and "128" in low)):
        return (
            "macOS denied the daemon access to the repo folder (TCC). The "
            "project's repo lives under a protected folder (Desktop/Documents/"
            "Downloads). Connect this project as a git workspace (clone by URL) "
            "so the daemon owns its own working copy, or grant the daemon Full "
            f"Disk Access. [{msg}]"
        )
    if ("authentication failed" in low or "could not read username" in low
            or "terminal prompts disabled" in low or "403" in low
            or ("permission denied" in low and "publickey" in low)):
        return (
            "git authentication failed provisioning the workspace — provide "
            f"valid credentials/token for the remote. [{msg}]"
        )
    if ("not a git repository" in low or "does not exist" in low
            or "repository not found" in low or "not_found" in low
            or "not available" in low):
        return f"the workspace source is not a usable git repository. [{msg}]"
    return f"workspace provisioning failed. [{msg}]"
