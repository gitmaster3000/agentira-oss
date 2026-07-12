"""Backend-hosted CLI release check + self-update for the agentira-cli / daemon.

Customers install from their Agentira instance URL (Railway-hosted wheel).
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

_USER_AGENT = "agentira-cli"
_RELEASE_PATH = "/api/public/cli-release"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    install_spec: str
    install_sh_url: str = ""
    min_python: str = "3.11"


@dataclass(frozen=True)
class ReleaseFetchResult:
    release: Optional[ReleaseInfo]
    status: str  # ok | unreachable | not_available


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse semver-ish '0.1.2' / 'v0.1.2' into a comparable tuple."""
    raw = version_str.strip().removeprefix("v")
    parts: list[int] = []
    for segment in raw.split("."):
        m = re.match(r"(\d+)", segment)
        if not m:
            break
        parts.append(int(m.group(1)))
    return tuple(parts) if parts else (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _normalize_api_url(api_url: str) -> str:
    return (api_url or "").strip().rstrip("/")


def _fetch_release_json(api_url: str, *, timeout: float = 15.0) -> dict:
    base = _normalize_api_url(api_url)
    if not base:
        raise ValueError("api_url required")
    url = f"{base}{_RELEASE_PATH}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        data = json.loads(resp.read().decode())
    if not isinstance(data, dict) or not data.get("version") or not data.get("install_url"):
        raise ValueError("invalid cli-release payload")
    return data


def fetch_latest_cli_release_result(*, api_url: str) -> ReleaseFetchResult:
    """Return the instance's published CLI release plus fetch status."""
    try:
        data = _fetch_release_json(api_url)
    except urllib.error.HTTPError as exc:
        logger.debug("cli-release HTTP %s: %s", exc.code, exc)
        if exc.code == 404:
            return ReleaseFetchResult(None, "not_available")
        return ReleaseFetchResult(None, "unreachable")
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("cli-release fetch failed: %s", exc)
        if isinstance(exc, ValueError) and "api_url required" in str(exc):
            return ReleaseFetchResult(None, "not_available")
        return ReleaseFetchResult(None, "unreachable")

    release = ReleaseInfo(
        version=str(data["version"]),
        install_spec=str(data["install_url"]),
        install_sh_url=str(data.get("install_sh_url") or ""),
        min_python=str(data.get("min_python") or "3.11"),
    )
    return ReleaseFetchResult(release, "ok")


def fetch_latest_cli_release(*, api_url: str) -> Optional[ReleaseInfo]:
    return fetch_latest_cli_release_result(api_url=api_url).release


def _fetch_failure_message(api_url: str, current: str, status: str) -> str:
    base = _normalize_api_url(api_url) or "(no backend URL configured)"
    if status == "not_available":
        return (
            f"No CLI release is published on {base} (current {current}). "
            f"The operator may need to redeploy the backend."
        )
    return (
        f"Could not reach {base}{_RELEASE_PATH} (current {current}). "
        f"Check AGENTIRA_DAEMON_API_URL and try again."
    )


def check_for_update(
    *, api_url: str, current: str | None = None,
) -> tuple[str, Optional[ReleaseInfo], str]:
    """Return (current_version, latest_release_or_none, fetch_status)."""
    cur = current or get_version()
    result = fetch_latest_cli_release_result(api_url=api_url)
    latest = result.release
    if latest is None:
        return cur, None, result.status
    if is_newer(latest.version, cur):
        return cur, latest, result.status
    return cur, None, result.status


def pip_install_upgrade(install_spec: str, *, python: str | None = None) -> subprocess.CompletedProcess:
    """Upgrade agentira-cli into the interpreter that runs the CLI."""
    exe = python or sys.executable
    return subprocess.run(
        [exe, "-m", "pip", "install", "--upgrade", install_spec],
        capture_output=True,
        text=True,
        check=False,
    )


def run_update(
    *, api_url: str, yes: bool = False, check_only: bool = False,
) -> dict:
    """Check the backend and optionally pip-install the published CLI wheel."""
    current, pending, status = check_for_update(api_url=api_url)
    out: dict = {
        "current": current,
        "latest": None,
        "updated": False,
        "message": "",
    }
    if pending is None:
        if status != "ok":
            out["message"] = _fetch_failure_message(api_url, current, status)
        else:
            out["message"] = f"Already on the latest release ({current})."
        return out

    out["latest"] = pending.version
    out["install_spec"] = pending.install_spec
    if pending.install_sh_url:
        out["install_sh_url"] = pending.install_sh_url

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


def startup_update_notice(
    cache_path, *, api_url: str, interval_hours: float = 24.0,
) -> None:
    """Best-effort background check; logs a hint when a release is newer."""
    if not should_check_now(cache_path, interval_hours=interval_hours):
        return

    def _work() -> None:
        try:
            current, pending, _status = check_for_update(api_url=api_url)
            write_check_cache(
                cache_path,
                current=current,
                latest=pending.version if pending else None,
            )
            if pending:
                logger.warning(
                    "agentira-cli %s is available (you have %s). "
                    "Run `agentira daemon update` to upgrade.",
                    pending.version, current,
                )
            else:
                logger.info("agentira-cli %s — up to date", current)
        except Exception as exc:  # noqa: BLE001
            logger.debug("startup update check failed: %s", exc)

    import threading
    threading.Thread(target=_work, name="update-check", daemon=True).start()