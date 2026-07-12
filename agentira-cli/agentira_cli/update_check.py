"""GitHub release check + self-update for the agentira-cli / daemon.

Customers install via `pip install agentira-cli` (or a release wheel).
`agentira daemon update` upgrades in-place using the same Python that
runs the CLI. On daemon startup we log when a newer release exists.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from agentira_cli._version import get_version
from agentira_cli.transport.tls import ssl_context

logger = logging.getLogger("agentira.update")

# Override for forks / staging: AGENTIRA_GITHUB_REPO=owner/repo
_DEFAULT_REPO = "gitmaster3000/agentira"
TAG_PREFIX = "agentira-cli-v"
_USER_AGENT = "agentira-cli"


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: str
    name: str
    html_url: str
    install_spec: str
    published_at: str = ""


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse semver-ish '0.1.2' / 'v0.1.2' into a comparable tuple."""
    raw = version_str.strip().removeprefix("v")
    if raw.startswith(TAG_PREFIX):
        raw = raw[len(TAG_PREFIX):]
    parts: list[int] = []
    for segment in raw.split("."):
        m = re.match(r"(\d+)", segment)
        if not m:
            break
        parts.append(int(m.group(1)))
    return tuple(parts) if parts else (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _github_repo() -> str:
    return (os.environ.get("AGENTIRA_GITHUB_REPO") or _DEFAULT_REPO).strip()


def _api_get(path: str, timeout: float = 15.0) -> object:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return json.loads(resp.read().decode())


def _install_spec_for_release(repo: str, release: dict) -> str:
    tag = release.get("tag_name") or ""
    for asset in release.get("assets") or []:
        name = (asset.get("name") or "")
        if name.endswith(".whl") and "agentira" in name.lower():
            url = asset.get("browser_download_url")
            if url:
                return url
    if tag:
        return (
            f"git+https://github.com/{repo}.git@{tag}"
            "#subdirectory=agentira-cli"
        )
    raise ValueError("release has no installable asset or tag")


def fetch_latest_cli_release(*, repo: str | None = None) -> Optional[ReleaseInfo]:
    """Return the newest GitHub release tagged agentira-cli-v*, or None."""
    repo = repo or _github_repo()
    try:
        data = _api_get(f"/repos/{repo}/releases?per_page=30")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.debug("release fetch failed: %s", exc)
        return None
    if not isinstance(data, list):
        return None

    candidates: list[ReleaseInfo] = []
    for rel in data:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tag = rel.get("tag_name") or ""
        if not tag.startswith(TAG_PREFIX):
            continue
        ver = tag[len(TAG_PREFIX):]
        try:
            spec = _install_spec_for_release(repo, rel)
        except ValueError:
            continue
        candidates.append(ReleaseInfo(
            tag=tag,
            version=ver,
            name=rel.get("name") or tag,
            html_url=rel.get("html_url") or "",
            install_spec=spec,
            published_at=rel.get("published_at") or "",
        ))

    if not candidates:
        return None
    candidates.sort(key=lambda r: parse_version(r.version), reverse=True)
    return candidates[0]


def check_for_update(*, current: str | None = None) -> tuple[str, Optional[ReleaseInfo]]:
    """Return (current_version, latest_release_or_none_if_up_to_date)."""
    cur = current or get_version()
    latest = fetch_latest_cli_release()
    if latest is None:
        return cur, None
    if is_newer(latest.version, cur):
        return cur, latest
    return cur, None


def pip_install_upgrade(install_spec: str, *, python: str | None = None) -> subprocess.CompletedProcess:
    """Upgrade agentira-cli into the interpreter that runs the CLI."""
    exe = python or sys.executable
    return subprocess.run(
        [exe, "-m", "pip", "install", "--upgrade", install_spec],
        capture_output=True,
        text=True,
        check=False,
    )


def run_update(*, yes: bool = False, check_only: bool = False) -> dict:
    """Check GitHub and optionally pip-install the latest CLI release."""
    current, pending = check_for_update()
    out: dict = {
        "current": current,
        "latest": None,
        "updated": False,
        "message": "",
    }
    if pending is None:
        if fetch_latest_cli_release() is None:
            out["message"] = (
                f"Could not reach GitHub releases for {_github_repo()} "
                f"(current {current}). Try again later."
            )
        else:
            out["message"] = f"Already on the latest release ({current})."
        return out

    out["latest"] = pending.version
    out["release_url"] = pending.html_url
    out["install_spec"] = pending.install_spec

    if check_only:
        out["message"] = (
            f"Update available: {current} → {pending.version}. "
            f"Run `agentira daemon update` to install."
        )
        return out

    if not yes:
        out["message"] = "confirmation_required"
        return out

    proc = pip_install_upgrade(pending.install_spec)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "pip failed").strip()
        out["message"] = f"Update failed: {err[:800]}"
        return out

    new_ver = get_version()
    out["updated"] = True
    out["current"] = new_ver
    out["message"] = f"Updated to {new_ver}. Restart the daemon: `agentira daemon restart`"
    return out


def should_check_now(cache_path, *, interval_hours: float = 24.0) -> bool:
    if os.environ.get("AGENTIRA_SKIP_UPDATE_CHECK", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return False
    if not cache_path.exists():
        return True
    try:
        data = json.loads(cache_path.read_text())
        last = float(data.get("checked_at", 0))
    except (OSError, ValueError, TypeError):
        return True
    return (time.time() - last) >= interval_hours * 3600


def write_check_cache(cache_path, *, current: str, latest: str | None) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "checked_at": time.time(),
            "current": current,
            "latest": latest,
        }))
    except OSError as exc:
        logger.debug("update cache write failed: %s", exc)


def startup_update_notice(cache_path, *, interval_hours: float = 24.0) -> None:
    """Best-effort background check; logs a hint when a release is newer."""
    if not should_check_now(cache_path, interval_hours=interval_hours):
        return

    def _work() -> None:
        try:
            current, pending = check_for_update()
            write_check_cache(
                cache_path,
                current=current,
                latest=pending.version if pending else None,
            )
            if pending:
                logger.warning(
                    "agentira-cli %s is available (you have %s). "
                    "Run `agentira daemon update` to upgrade. %s",
                    pending.version, current, pending.html_url,
                )
            else:
                logger.info("agentira-cli %s — up to date", current)
        except Exception as exc:  # noqa: BLE001
            logger.debug("startup update check failed: %s", exc)

    import threading
    threading.Thread(target=_work, name="update-check", daemon=True).start()