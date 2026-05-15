"""Tests for the dispatch-handler timeout + per-step logging.

When materialize() or ensure_memory_dirs() hangs (NFS, slow disk, hung
git), the trigger handler used to silently never spawn the subprocess.
Failure mode: WS log shows 'trigger received' but no 'recv trigger'
follow-up, no subprocess in `ps`. From the user's POV the agent goes
permanently quiet.

The fix wraps each filesystem step in asyncio.wait_for and posts a
synthetic trigger-complete with a clear error when timeouts fire. These
tests prove that wiring."""

from __future__ import annotations

import asyncio
import time
from unittest import mock

import pytest


@pytest.fixture()
def daemon_instance(monkeypatch):
    """A minimally-constructed AgentiraDaemon with the network/IO bits stubbed.
    We don't run its main loop — we just call _execute directly to test the
    setup-failure code path."""
    from agentira_cli.daemon.core import AgentiraDaemon

    # Avoid loading config from env / disk
    monkeypatch.setattr(
        "agentira_cli.state.config.DaemonConfig",
        lambda *a, **kw: mock.MagicMock(
            api_url="http://localhost:8111",
            api_key="test",
            log_level="INFO",
            dry_run=False,
            device_name="test-host",
            max_concurrent=1,
        ),
    )

    cfg = mock.MagicMock(
        api_url="http://localhost:8111",
        api_key="test",
        log_level="INFO",
        dry_run=False,
        device_name="test-host",
        max_concurrent=1,
    )
    d = AgentiraDaemon.__new__(AgentiraDaemon)
    # Minimal init — just the attributes _execute / _post_setup_failure touch
    d.config = cfg
    d._daemon_id = "test-daemon"
    d._registered = [{
        "provider": "claude",
        "binary_path": "/fake/claude",
        "capabilities": [],
        "models": [],
    }]
    d._inflight = {}
    d._inflight_lock = __import__("threading").Lock()
    d._run_to_trace = {}
    d.client = mock.MagicMock()
    return d


def test_setup_timeout_surfaces_as_run_failure(daemon_instance, monkeypatch):
    """If materialize() blocks past the 30s budget (simulated here with
    asyncio.sleep), the handler must post a trigger-complete with a
    descriptive error — not silently abandon the run."""
    from agentira_cli.daemon import core as core_mod

    # Patch materialize to sleep past the wait_for budget. Asyncio
    # detaches when the timeout fires; the thread eventually completes
    # on its own. Keep the sleep short so the test suite stays fast.
    def slow_materialize(**kwargs):
        time.sleep(2.0)
        return ("/tmp/never", {})

    monkeypatch.setattr(
        "agentira_cli.daemon.materializer.materialize", slow_materialize,
    )
    monkeypatch.setattr(
        "agentira_cli.daemon.materializer.ensure_memory_dirs", lambda *a: None,
    )
    monkeypatch.setattr(
        "agentira_cli.daemon.materializer.compose_system_prompt",
        lambda *a, **kw: "sys",
    )

    # Patch the timeout down to something testable
    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, timeout):
        return await original_wait_for(coro, timeout=0.5)  # 500ms

    monkeypatch.setattr("asyncio.wait_for", fast_wait_for)

    # Force the run_id+task_id path so materialize is hit
    frame = {
        "trace_id": "test-trace",
        "run_id": "test-run",
        "agent_id": "test-agent",
        "prompt": "hi",
        "provider": "claude",
        "kind": "run_step",
        "repo_path": "/fake/repo",
        "conventions_md": "",
        "mcp_config_json": "",
        "env_extra": {"AGENTIRA_TASK_ID": "test-task"},
    }

    asyncio.run(daemon_instance._execute(frame))

    # post_trigger_complete should have been called with success=False and
    # a setup-failure error string.
    daemon_instance.client.post_trigger_complete.assert_called_once()
    kwargs = daemon_instance.client.post_trigger_complete.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["trace_id"] == "test-trace"
    assert kwargs["run_id"] == "test-run"
    assert "setup" in kwargs["error"].lower(), \
        f"Expected setup-failure error, got: {kwargs['error']!r}"


def test_setup_exception_surfaces_as_run_failure(daemon_instance, monkeypatch):
    """If materialize() raises (e.g. permission denied, disk full),
    the handler must convert that into a trigger-complete error event."""
    monkeypatch.setattr(
        "agentira_cli.daemon.materializer.materialize",
        lambda **kw: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        "agentira_cli.daemon.materializer.ensure_memory_dirs", lambda *a: None,
    )
    monkeypatch.setattr(
        "agentira_cli.daemon.materializer.compose_system_prompt",
        lambda *a, **kw: "sys",
    )

    frame = {
        "trace_id": "test-trace-2",
        "run_id": "test-run-2",
        "agent_id": "test-agent",
        "prompt": "hi",
        "provider": "claude",
        "kind": "run_step",
        "repo_path": "/fake/repo",
        "env_extra": {"AGENTIRA_TASK_ID": "test-task"},
    }
    asyncio.run(daemon_instance._execute(frame))

    daemon_instance.client.post_trigger_complete.assert_called_once()
    kwargs = daemon_instance.client.post_trigger_complete.call_args.kwargs
    assert kwargs["success"] is False
    assert "disk full" in kwargs["error"].lower() or "setup" in kwargs["error"].lower()


def test_unknown_provider_returns_early(daemon_instance):
    """Frame with unknown provider should not crash — just log and return."""
    frame = {
        "trace_id": "trace-x",
        "agent_id": "test-agent",
        "prompt": "hi",
        "provider": "nonexistent-runtime",
        "kind": "chat",
    }
    # Shouldn't raise
    asyncio.run(daemon_instance._execute(frame))
    daemon_instance.client.post_trigger_complete.assert_not_called()
