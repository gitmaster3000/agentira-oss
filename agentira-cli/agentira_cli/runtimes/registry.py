from __future__ import annotations

from .base import DetectedRuntime, Runtime
from .claude import ClaudeRuntime
from .codex import CodexRuntime
from .gemini import GeminiRuntime
from .grok import GrokRuntime
from .opencode import OpenCodeRuntime
from .openclaw import OpenClawRuntime
from .ollama import OllamaRuntime

SUPPORTED: list[type[Runtime]] = [
    ClaudeRuntime,
    CodexRuntime,
    GeminiRuntime,
    GrokRuntime,
    OpenCodeRuntime,
    OpenClawRuntime,
    OllamaRuntime,
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
