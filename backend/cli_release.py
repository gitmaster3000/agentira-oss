"""Public CLI release artifacts — served from the Railway backend image.

Customers install/upgrade via their Agentira instance URL (no GitHub access).
Wheels are baked into the Docker image at build time; manifest.json records
the version + filename.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

router = APIRouter(prefix="/api/public", tags=["public-cli"])

_WHEEL_NAME = re.compile(r"^agentira_cli-[\w.+]+-py3-none-any\.whl$")


def cli_static_root() -> Path:
    override = (os.environ.get("AGENTIRA_CLI_STATIC_DIR") or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "static" / "cli"


def _manifest_path() -> Path:
    return cli_static_root() / "manifest.json"


def _wheels_dir() -> Path:
    return cli_static_root() / "wheels"


def load_manifest() -> dict:
    path = _manifest_path()
    if not path.is_file():
        raise FileNotFoundError("cli manifest missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("version") or not data.get("wheel_filename"):
        raise ValueError("cli manifest invalid")
    return data


def public_base_url(request: Request) -> str:
    override = (os.environ.get("AGENTIRA_PUBLIC_URL") or "").strip().rstrip("/")
    if override:
        return override
    scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0]
    host = (request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.netloc or "").split(",")[0]
    return f"{scheme}://{host}".rstrip("/")


def cli_release_payload(request: Request) -> dict:
    manifest = load_manifest()
    base = public_base_url(request)
    wheel = manifest["wheel_filename"]
    return {
        "version": manifest["version"],
        "min_python": manifest.get("min_python", "3.11"),
        "install_url": f"{base}/api/public/cli/wheels/{wheel}",
        "install_sh_url": f"{base}/api/public/install.sh",
        "install_ps1_url": f"{base}/api/public/install.ps1",
    }


def resolve_wheel(filename: str) -> Path | None:
    name = Path(filename).name
    if not _WHEEL_NAME.match(name):
        return None
    path = _wheels_dir() / name
    return path if path.is_file() else None


@router.get("/cli-release")
def api_cli_release(request: Request):
    try:
        return cli_release_payload(request)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        raise HTTPException(404, "CLI release not available on this instance")


@router.get("/cli/wheels/{filename}")
def api_cli_wheel(filename: str):
    path = resolve_wheel(filename)
    if path is None:
        raise HTTPException(404, "wheel not found")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=path.name,
    )


def _installer_script(name: str, media_type: str) -> PlainTextResponse:
    script = Path(__file__).resolve().parents[1] / "scripts" / name
    if not script.is_file():
        raise HTTPException(404, "installer script missing")
    return PlainTextResponse(script.read_text(encoding="utf-8"), media_type=media_type)


@router.get("/install.sh")
def api_install_sh():
    return _installer_script("install-daemon.sh", "text/x-shellscript; charset=utf-8")


@router.get("/install.ps1")
def api_install_ps1():
    return _installer_script("install-daemon.ps1", "text/plain; charset=utf-8")