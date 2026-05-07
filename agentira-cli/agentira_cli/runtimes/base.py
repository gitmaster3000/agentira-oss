from __future__ import annotations

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class DetectedRuntime:
    provider: str
    binary_path: str
    version: str | None
    capabilities: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    gateway_url: str = ""
    gateway_token: str = ""


class Runtime:
    """Base class for a CLI runtime provider.

    Subclasses set class attrs and override build_args/parse_event in later phases.
    """

    provider: ClassVar[str] = ""
    default_binary: ClassVar[str] = ""
    env_path_override: ClassVar[str] = ""  # e.g. "AGENTIRA_CLAUDE_PATH"
    version_args: ClassVar[tuple[str, ...]] = ("--version",)
    capabilities: ClassVar[tuple[str, ...]] = ()
    fallback_paths: ClassVar[tuple[str, ...]] = ()  # absolute paths to probe if not on PATH
    models: ClassVar[tuple[str, ...]] = ()  # supported model identifiers (first = default)

    @classmethod
    def build_args(cls, prompt: str, **kwargs) -> list[str]:
        raise NotImplementedError

    @classmethod
    def parse_event(cls, line: str):
        return None

    @classmethod
    def introspect(cls, binary_path: str) -> dict:
        """Optional: query a running runtime for live config (gateway URL, token, models).
        Override in gateway-type runtimes. Returns {} by default."""
        return {}

    @classmethod
    def detect(cls) -> DetectedRuntime | None:
        override = os.environ.get(cls.env_path_override)
        if override:
            path = shutil.which(override) or (override if os.path.isfile(override) and os.access(override, os.X_OK) else None)
        else:
            path = shutil.which(cls.default_binary)
            if not path:
                for fp in cls.fallback_paths:
                    expanded = os.path.expanduser(fp)
                    matches = sorted(glob.glob(expanded), reverse=True) if any(c in expanded for c in "*?[") else [expanded]
                    for m in matches:
                        if os.path.isfile(m) and os.access(m, os.X_OK):
                            path = m
                            break
                    if path:
                        break
        if not path:
            return None
        extra = cls.introspect(path)
        return DetectedRuntime(
            provider=cls.provider,
            binary_path=path,
            version=cls._read_version(path),
            capabilities=list(cls.capabilities),
            models=extra.get("models") or list(cls.models),
            gateway_url=extra.get("gateway_url", ""),
            gateway_token=extra.get("gateway_token", ""),
        )

    @classmethod
    def _read_version(cls, path: str) -> str | None:
        try:
            out = subprocess.run(
                [path, *cls.version_args],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        text = (out.stdout or out.stderr).strip()
        return text.splitlines()[0] if text else None
