"""Runtime Adapter contract (ADR 009).

Every adapter declares capabilities and may override the contract methods
(`derive_session_handle`, `clear_handle`) — the upper layers backfill
whatever isn't natively supported. These tests guard the *contract*, not
the wire-level integration (that's per-adapter, behind real providers).
"""

from __future__ import annotations

import pytest

from agentira_cli.runtimes.base import (
    Capability, Runtime, derive_session_handle,
)
from agentira_cli.runtimes.claude import ClaudeRuntime
from agentira_cli.runtimes.codex import CodexRuntime
from agentira_cli.runtimes.gemini import GeminiRuntime
from agentira_cli.runtimes.grok import GrokRuntime
from agentira_cli.runtimes.ollama import OllamaRuntime
from agentira_cli.runtimes.openclaw import OpenClawRuntime
from agentira_cli.runtimes.opencode import OpenCodeRuntime


ALL_RUNTIMES = [
    ClaudeRuntime, CodexRuntime, GeminiRuntime, GrokRuntime, OllamaRuntime,
    OpenClawRuntime, OpenCodeRuntime,
]


# ── derive_session_handle ─────────────────────────────────────────────────

def test_derive_handle_is_deterministic_per_scope():
    h1 = derive_session_handle(agent_id="abcdef1234567890", scope_key="task:t1")
    h2 = derive_session_handle(agent_id="abcdef1234567890", scope_key="task:t1")
    assert h1 == h2 != ""


def test_derive_handle_isolates_per_scope_and_per_agent():
    a, b = "aaaaaaaa11111111", "bbbbbbbb22222222"
    keys = ["task:t1", "task:t2", "chat:project:p1", "chat:default"]
    handles = {(a, k): derive_session_handle(agent_id=a, scope_key=k) for k in keys}
    handles |= {(b, k): derive_session_handle(agent_id=b, scope_key=k) for k in keys}
    # All distinct — neither scope nor agent collide.
    assert len(set(handles.values())) == len(handles)


def test_derive_handle_sanitizes_unsafe_chars():
    h = derive_session_handle(agent_id="abcdef12", scope_key="task:weird path /\\ÿ")
    # Result stays a flat printable token (no whitespace, no slashes).
    assert " " not in h and "/" not in h and "\\" not in h


def test_derive_handle_empty_inputs_returns_empty():
    assert derive_session_handle(agent_id="", scope_key="task:t1") == ""
    assert derive_session_handle(agent_id="abcdef12", scope_key="") == ""


# ── Runtime contract ──────────────────────────────────────────────────────

@pytest.mark.parametrize("rt", ALL_RUNTIMES)
def test_every_adapter_implements_the_contract(rt):
    """Every adapter must expose the four contract surfaces — base supplies
    safe defaults so this just checks they're inherited / overridden."""
    assert isinstance(rt.capabilities, tuple)
    # Methods exist and are callable with the documented kwargs.
    assert callable(rt.derive_session_handle)
    assert callable(rt.clear_handle)
    assert callable(rt.build_args)
    # clear_handle is a safe no-op by default.
    assert rt.clear_handle(agent_id="x", scope_key="task:t") is None


def test_openclaw_derives_a_real_session_key():
    """OpenClaw's native continuity is sessionKey — adapter must return one."""
    h = OpenClawRuntime.derive_session_handle(
        agent_id="abcdef1234567890", scope_key="task:t1")
    assert h.startswith("agentira:abcdef12:task:t1")


def test_runtimes_without_native_resume_return_empty_handle():
    """Adapters whose providers have no string-keyed thread (claude is
    cwd-keyed, ollama/bare LLM has nothing) return "" so the backend
    falls back to history-replay."""
    for rt in (ClaudeRuntime, OllamaRuntime, GeminiRuntime):
        assert rt.derive_session_handle(
            agent_id="abcdef12", scope_key="task:t1") == ""


# ── Capability flags ──────────────────────────────────────────────────────

def test_capability_constants_match_legacy_strings():
    # The string literals already in use must equal the constants.
    assert Capability.RESUME == "resume"
    assert Capability.STREAM_JSON == "stream_json"
    assert Capability.HTTP_GATEWAY == "http_gateway"
    assert Capability.MCP_CONFIG == "mcp_config"
    assert Capability.COMPACT == "compact"


# ── compaction (AP-190) ───────────────────────────────────────────────────

@pytest.mark.parametrize("rt", ALL_RUNTIMES)
def test_every_adapter_exposes_a_compact_instruction(rt):
    """The compaction contract is portable — every adapter returns a non-empty
    instruction usable as a normal resumed turn, even without native /compact."""
    instr = rt.compact_instruction()
    assert isinstance(instr, str) and instr.strip()


def test_claude_advertises_native_compact():
    assert Capability.COMPACT in ClaudeRuntime.capabilities


def test_every_advertised_capability_is_a_known_flag():
    """Each adapter's declared capabilities must be values from
    Capability — catches typos when adapters are added."""
    known = Capability.all()
    for rt in ALL_RUNTIMES:
        for cap in rt.capabilities:
            assert cap in known, f"{rt.__name__} declares unknown capability {cap!r}"
