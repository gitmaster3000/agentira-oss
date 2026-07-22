"""CodexRuntime adapter — build_args + `codex exec --json` stream parsing.

Mirrors the grok/claude adapter shape: CLI detection is inherited from the
base Runtime, so these tests pin the codex-specific wire mapping — the
`codex exec` argv it builds and the JSONL events it decodes into the shared
stream event dataclasses the executor drains.
"""

from __future__ import annotations

import json

from agentira_cli.runtimes.claude import (
    ResultEvent,
    SessionEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from agentira_cli.runtimes.codex import CodexRuntime


# ── build_args ────────────────────────────────────────────────────────────

def test_build_args_basic_exec_stream_json():
    args = CodexRuntime.build_args("do the thing")
    assert args[0] == "exec"
    assert "--json" in args
    assert "--skip-git-repo-check" in args
    assert "--dangerously-bypass-approvals-and-sandbox" in args
    # Prompt is the trailing positional.
    assert args[-1] == "do the thing"
    # No resume subcommand on a fresh turn.
    assert "resume" not in args


def test_build_args_model_flag():
    args = CodexRuntime.build_args("hi", model="gpt-5-codex")
    i = args.index("-m")
    assert args[i + 1] == "gpt-5-codex"


def test_build_args_system_prompt_is_prepended():
    args = CodexRuntime.build_args("user ask", system_prompt="You are terse.")
    prompt = args[-1]
    assert prompt.startswith("You are terse.")
    assert prompt.endswith("user ask")
    assert "user ask" in prompt


def test_build_args_resume_uses_resume_subcommand():
    sid = "019f8883-a1db-7a63-94b8-9bfa3d9fe5ef"
    args = CodexRuntime.build_args("continue", resume_session_id=sid)
    assert args[:3] == ["exec", "resume", sid]
    assert "--json" in args
    assert args[-1] == "continue"


def test_build_args_ignores_unsupported_claude_flags():
    # Codex has no --mcp-config / --allowed-tools / --max-turns surface; the
    # adapter must accept those kwargs (executor passes them) without emitting
    # bogus flags.
    args = CodexRuntime.build_args(
        "x",
        mcp_config_path="/tmp/mcp.json",
        mcp_strict=True,
        allowed_tools=("Read", "Bash"),
        max_turns=42,
    )
    assert "--mcp-config" not in args
    assert "--allowedTools" not in args
    assert "--allowed-tools" not in args
    assert "--max-turns" not in args


# ── parse_event ───────────────────────────────────────────────────────────

def _parse(obj):
    return CodexRuntime.parse_event(json.dumps(obj))


def test_parse_thread_started_is_session_event():
    ev = _parse({"type": "thread.started", "thread_id": "abc-123"})
    assert isinstance(ev, SessionEvent)
    assert ev.session_id == "abc-123"


def test_parse_turn_started_is_ignored():
    assert _parse({"type": "turn.started"}) is None


def test_parse_agent_message_is_text_event():
    ev = _parse({
        "type": "item.completed",
        "item": {"id": "item_0", "type": "agent_message", "text": "PONG"},
    })
    assert isinstance(ev, TextEvent)
    assert ev.text == "PONG"


def test_parse_command_started_is_tool_use():
    ev = _parse({
        "type": "item.started",
        "item": {"type": "command_execution", "command": "echo hi", "status": "in_progress"},
    })
    assert isinstance(ev, ToolUseEvent)
    assert ev.tool_name == "command_execution"
    assert ev.tool_input == "echo hi"


def test_parse_command_completed_is_tool_result_with_exit_code():
    ev = _parse({
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "echo hi",
            "aggregated_output": "hi\n",
            "exit_code": 0,
            "status": "completed",
        },
    })
    assert isinstance(ev, ToolResultEvent)
    assert "hi" in ev.output
    assert "[exit 0]" in ev.output


def test_parse_turn_completed_is_success_result_with_usage():
    ev = _parse({
        "type": "turn.completed",
        "usage": {"input_tokens": 100, "output_tokens": 6},
    })
    assert isinstance(ev, ResultEvent)
    assert ev.success is True
    assert ev.input_tokens == 100
    assert ev.output_tokens == 6


def test_parse_turn_failed_is_error_result():
    ev = _parse({
        "type": "turn.failed",
        "error": {"message": "model not supported for this account"},
    })
    assert isinstance(ev, ResultEvent)
    assert ev.success is False
    assert "not supported" in ev.error


def test_parse_top_level_error_is_error_result():
    ev = _parse({"type": "error", "message": "boom"})
    assert isinstance(ev, ResultEvent)
    assert ev.success is False
    assert ev.error == "boom"


def test_parse_garbage_line_is_none():
    assert CodexRuntime.parse_event("not json") is None
    assert CodexRuntime.parse_event("") is None


# ── capabilities / models ─────────────────────────────────────────────────

def test_declares_stream_json_and_resume():
    assert "stream_json" in CodexRuntime.capabilities
    assert "resume" in CodexRuntime.capabilities


def test_no_static_fallback_list():
    # No hardcoded models: discovery is the only source; absent it the UI
    # prompts for a free-form model rather than offering stale/dead SKUs.
    assert CodexRuntime.models == ()


def test_detect_models_empty_when_no_cache_or_override(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTIRA_CODEX_MODELS", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))  # no models_cache.json
    d = CodexRuntime.detect()
    if d is not None:  # codex may not be installed in CI
        assert d.models == []


def test_introspect_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTIRA_CODEX_MODELS", " a , b , ")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))  # override wins over cache
    assert CodexRuntime.introspect("/usr/bin/codex") == {"models": ["a", "b"]}


def test_introspect_empty_without_override_or_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTIRA_CODEX_MODELS", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))  # empty dir, no cache file
    assert CodexRuntime.introspect("/usr/bin/codex") == {}


# ── live model discovery via models_cache.json ────────────────────────────

def _write_cache(tmp_path, models):
    (tmp_path / "models_cache.json").write_text(json.dumps({
        "fetched_at": "2026-07-22T21:18:28Z",
        "models": models,
    }))


def test_discovery_reads_cache_filters_and_orders(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTIRA_CODEX_MODELS", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    _write_cache(tmp_path, [
        {"slug": "gpt-5.4", "visibility": "list", "priority": 16},
        {"slug": "gpt-5.6-sol", "visibility": "list", "priority": 1},
        {"slug": "codex-auto-review", "visibility": "hide", "priority": 43},
        {"slug": "gpt-5.5", "visibility": "list", "priority": 7},
    ])
    # Sorted by priority, hidden SKU dropped.
    assert CodexRuntime.introspect("/usr/bin/codex") == {
        "models": ["gpt-5.6-sol", "gpt-5.5", "gpt-5.4"]
    }


def test_discovery_override_beats_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTIRA_CODEX_MODELS", "pinned-model")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    _write_cache(tmp_path, [{"slug": "gpt-5.6-sol", "visibility": "list", "priority": 1}])
    assert CodexRuntime.introspect("/usr/bin/codex") == {"models": ["pinned-model"]}


def test_discovery_survives_corrupt_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTIRA_CODEX_MODELS", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text("{not json")
    assert CodexRuntime.introspect("/usr/bin/codex") == {}


def test_corrupt_cache_logs_a_warning(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("AGENTIRA_CODEX_MODELS", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text("{not json")
    with caplog.at_level("WARNING", logger="agentira.runtime.codex"):
        CodexRuntime.introspect("/usr/bin/codex")
    assert any("model discovery failed" in r.message for r in caplog.records)


def test_absent_cache_does_not_warn(monkeypatch, tmp_path, caplog):
    # Fresh install (codex never run) is normal, not an error — no warning.
    monkeypatch.delenv("AGENTIRA_CODEX_MODELS", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    with caplog.at_level("WARNING", logger="agentira.runtime.codex"):
        CodexRuntime.introspect("/usr/bin/codex")
    assert not any("discovery failed" in r.message for r in caplog.records)


def test_cache_hit_logs_source_path(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("AGENTIRA_CODEX_MODELS", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    _write_cache(tmp_path, [{"slug": "gpt-5.6-sol", "visibility": "list", "priority": 1}])
    with caplog.at_level("INFO", logger="agentira.runtime.codex"):
        CodexRuntime.introspect("/usr/bin/codex")
    assert any("source=" in r.message and "models_cache.json" in r.message
               for r in caplog.records)
