from __future__ import annotations

from .base import DetectedRuntime, Runtime
from .claude import ClaudeRuntime
from .codex import CodexRuntime
from .gemini import GeminiRuntime
from .opencode import OpenCodeRuntime
from .openclaw import OpenClawRuntime

SUPPORTED: list[type[Runtime]] = [
    ClaudeRuntime,
    CodexRuntime,
    GeminiRuntime,
    OpenCodeRuntime,
    OpenClawRuntime,
]


def get_runtime_cls(provider: str) -> type[Runtime] | None:
    for cls in SUPPORTED:
        if cls.provider == provider:
            return cls
    return None


def detect_all() -> list[DetectedRuntime]:
    found: list[DetectedRuntime] = []
    for cls in SUPPORTED:
        rt = cls.detect()
        if rt is not None:
            found.append(rt)
    return found
