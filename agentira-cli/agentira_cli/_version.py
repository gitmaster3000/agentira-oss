"""Installed agentira-cli version (from package metadata)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    try:
        return version("agentira-cli")
    except PackageNotFoundError:
        return "0.0.0+unknown"