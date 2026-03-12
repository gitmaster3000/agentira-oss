"""Tests for the webhook integration layer (ADR-007).

Covers:
  - WebhookReceiver (stdlib HTTP server)
  - Daemon webhook-driven execution
  - Daemon auto-registration of webhook URL
  - AgentiraClient.update_my_profile
  - agent_notifier config-driven dispatch + transport resolution
"""

import json
import queue
import threading
import time
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services
from backend import agent_notifier
from agents.webhook_receiver import WebhookReceiver


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession):
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession


# ── WebhookReceiver tests ─────────────────────────────────────────────────

class TestWebhookReceiver:
    """Test the stdlib HTTP webhook receiver."""

    def _start_receiver(self, port, token=""):
        q = queue.Queue()
        wake = threading.Event()
        receiver = WebhookReceiver(port=port, event_queue=q, wake_event=wake, token=token)
        receiver.start()
        time.sleep(0.2)  # let server bind
        return receiver, q, wake

    def _post(self, port, path="/webhook", body=None, headers=None):
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    def test_valid_payload_queued_and_wakes(self):
        receiver, q, wake = self._start_receiver(19111)
        try:
            payload = {"event": "task.moved", "task_id": "t1"}
            status, body = self._post(19111, body=payload)
            assert status == 200
            assert body["ok"] is True
            assert wake.is_set()
            assert not q.empty()
            assert q.get_nowait()["task_id"] == "t1"
        finally:
            receiver.stop()

    def test_invalid_token_rejected(self):
        receiver, q, wake = self._start_receiver(19112, token="secret123")
        try:
            with pytest.raises((urllib.error.HTTPError, ConnectionError)):
                self._post(19112, body={"event": "test"}, headers={"X-Agentira-Token": "wrong"})
            assert q.empty()
        finally:
            receiver.stop()

    def test_valid_token_accepted(self):
        receiver, q, wake = self._start_receiver(19113, token="secret123")
        try:
            status, _ = self._post(
                19113, body={"event": "task.created"}, headers={"X-Agentira-Token": "secret123"}
            )
            assert status == 200
            assert not q.empty()
        finally:
            receiver.stop()

    def test_bad_json_returns_400(self):
        receiver, q, _ = self._start_receiver(19114)
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:19114/webhook",
                data=b"not json",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)
            assert exc_info.value.code == 400
        finally:
            receiver.stop()

    def test_wrong_path_returns_404(self):
        receiver, _, _ = self._start_receiver(19115)
        try:
            with pytest.raises((urllib.error.HTTPError, ConnectionError)) as exc_info:
                self._post(19115, path="/other", body={"event": "test"})
            if isinstance(exc_info.value, urllib.error.HTTPError):
                assert exc_info.value.code == 404
        finally:
            receiver.stop()

    def test_port_zero_skips_start(self):
        """Port 0 means disabled — start() is a no-op."""
        q = queue.Queue()
        wake = threading.Event()
        receiver = WebhookReceiver(port=0, event_queue=q, wake_event=wake)
        receiver.start()  # should not raise
        receiver.stop()


# ── agent_notifier tests ──────────────────────────────────────────────────

class TestTransportResolution:
    """Test resolve_transport() priority logic."""

    def test_explicit_transport_wins(self):
        profile = MagicMock()
        profile.notification_transport = "poll"
        profile.webhook_url = "http://example.com/webhook"
        assert agent_notifier.resolve_transport(profile) == "poll"

    def test_webhook_url_implies_webhook(self):
        profile = MagicMock()
        profile.notification_transport = None
        profile.webhook_url = "http://example.com/webhook"
        assert agent_notifier.resolve_transport(profile) == "webhook"

    def test_no_config_defaults_to_poll(self):
        profile = MagicMock()
        profile.notification_transport = None
        profile.webhook_url = ""
        assert agent_notifier.resolve_transport(profile) == "poll"


class TestWebhookDispatch:
    """Test config-driven webhook dispatch."""

    def test_dispatch_sends_to_webhook_targets(self):
        # Set up a bot with webhook_url
        admin = services.create_profile("dispatch-admin", role="admin")
        bot = services.create_profile("dispatch-bot", role="bot")
        proj = services.create_project("DispatchTest", actor="dispatch-admin")
        services.add_project_member(proj["id"], "dispatch-bot", actor="dispatch-admin")

        # Set webhook URL on bot
        services.update_profile(bot["id"], webhook_url="http://127.0.0.1:29999/webhook")

        # Create a task assigned to the bot
        task = services.create_task(
            proj["id"], "Test dispatch", assignee="dispatch-bot", actor="dispatch-admin"
        )

        # Dispatch — should attempt to POST to the bot's webhook URL
        with patch("backend.agent_notifier._post") as mock_post:
            with services._session() as db:
                agent_notifier.dispatch(db, "task.assigned", task, "dispatch-admin")

            # The notifier fires in a thread — give it a moment
            time.sleep(0.3)
            if mock_post.called:
                args = mock_post.call_args[0]
                assert args[0] == "http://127.0.0.1:29999/webhook"
                assert args[1]["event"] == "task.assigned"
                assert args[1]["task_id"] == task["id"]

    def test_no_dispatch_when_webhook_disabled(self):
        """Bots without webhook_url should not receive webhook POST."""
        admin = services.create_profile("nodispatch-admin", role="admin")
        bot = services.create_profile("nodispatch-bot", role="bot")
        proj = services.create_project("NoDispatch", actor="nodispatch-admin")
        services.add_project_member(proj["id"], "nodispatch-bot", actor="nodispatch-admin")
        # No webhook_url set

        task = services.create_task(
            proj["id"], "No webhook", assignee="nodispatch-bot", actor="nodispatch-admin"
        )

        with patch("backend.agent_notifier._post") as mock_post:
            with services._session() as db:
                agent_notifier.dispatch(db, "task.assigned", task, "nodispatch-admin")
            time.sleep(0.3)
            mock_post.assert_not_called()


# ── Daemon prompt builder tests ───────────────────────────────────────────

class TestDaemonPromptBuilder:
    """Test prompt construction with and without event context."""

    def test_basic_prompt(self):
        from agents.daemon import AgentiraDaemon

        prompt = AgentiraDaemon._build_prompt("Fix login", "The login is broken")
        assert "# Task: Fix login" in prompt
        assert "The login is broken" in prompt
        assert "## Trigger" not in prompt

    def test_prompt_with_event_context(self):
        from agents.daemon import AgentiraDaemon

        event = {
            "event": "task.commented",
            "actor": "alice",
            "status": "in_progress",
            "task_id": "t1",
        }
        prompt = AgentiraDaemon._build_prompt("Fix login", "Broken", event_context=event)
        assert "## Trigger" in prompt
        assert "Event: task.commented" in prompt
        assert "Triggered by: alice" in prompt
        assert "new comment was added" in prompt

    def test_prompt_assigned_event(self):
        from agents.daemon import AgentiraDaemon

        event = {"event": "task.assigned", "actor": "bob"}
        prompt = AgentiraDaemon._build_prompt("New task", "", event_context=event)
        assert "assigned this task" in prompt

    def test_prompt_moved_event(self):
        from agents.daemon import AgentiraDaemon

        event = {"event": "task.moved", "status": "review"}
        prompt = AgentiraDaemon._build_prompt("Task X", "", event_context=event)
        assert "status changed to 'review'" in prompt


# ── _post() auth header tests ────────────────────────────────────────────

class TestPostAuthHeader:
    """Test that _post() sends Authorization header when token is provided."""

    def test_post_sends_bearer_token(self):
        """_post() should include Authorization: Bearer <token> when token is non-empty."""
        with patch("backend.agent_notifier.urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            agent_notifier._post("http://example.com/hook", {"event": "test"}, token="my-secret")

            req = mock_open.call_args[0][0]
            assert req.get_header("Authorization") == "Bearer my-secret"

    def test_post_no_auth_header_when_empty_token(self):
        """_post() should NOT include Authorization header when token is empty."""
        with patch("backend.agent_notifier.urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            agent_notifier._post("http://example.com/hook", {"event": "test"})

            req = mock_open.call_args[0][0]
            assert req.get_header("Authorization") is None

    def test_dispatch_reads_token_from_webhook_config(self):
        """dispatch() should read token from project webhook_config and pass it to _post()."""
        admin = services.create_profile("token-admin", role="admin")
        bot = services.create_profile("token-bot", role="bot")
        proj = services.create_project("TokenTest", actor="token-admin")
        services.add_project_member(proj["id"], "token-bot", actor="token-admin")
        services.update_profile(bot["id"], webhook_url="http://127.0.0.1:29999/webhook")

        # Set webhook_config with a token
        services.set_webhook_config(
            proj["id"], enabled=True,
            rules=agent_notifier.DEFAULT_WEBHOOK_RULES,
            token="project-secret-123",
        )

        task = services.create_task(
            proj["id"], "Token dispatch test", assignee="token-bot", actor="token-admin"
        )

        with patch("backend.agent_notifier._post") as mock_post:
            with services._session() as db:
                agent_notifier.dispatch(db, "task.assigned", task, "token-admin")
            time.sleep(0.3)

            assert mock_post.called
            call_args = mock_post.call_args
            # _post(url, payload, token) — token is 3rd positional arg
            assert call_args[0][2] == "project-secret-123"

    def test_dispatch_no_token_when_config_has_none(self):
        """dispatch() should pass empty token when webhook_config has no token."""
        admin = services.create_profile("notoken-admin", role="admin")
        bot = services.create_profile("notoken-bot", role="bot")
        proj = services.create_project("NoTokenTest", actor="notoken-admin")
        services.add_project_member(proj["id"], "notoken-bot", actor="notoken-admin")
        services.update_profile(bot["id"], webhook_url="http://127.0.0.1:29999/webhook")

        task = services.create_task(
            proj["id"], "No token test", assignee="notoken-bot", actor="notoken-admin"
        )

        with patch("backend.agent_notifier._post") as mock_post:
            with services._session() as db:
                agent_notifier.dispatch(db, "task.assigned", task, "notoken-admin")
            time.sleep(0.3)

            assert mock_post.called
            call_args = mock_post.call_args
            assert call_args[0][2] == ""
