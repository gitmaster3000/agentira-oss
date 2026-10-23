"""The daemon keeps itself signed in: proactive refresh (<24h left), refresh +
one retry on 401, and a rate-limited ERROR when it can't."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import stat
import urllib.error
from unittest import mock

import pytest

from agentira_cli.daemon.auth import SIGNED_OUT_MSG, TokenManager

NOW = 1_800_000_000.0
HOUR = 3600


def jwt_expiring_in(seconds: float) -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'HS256'})}.{b64({'exp': NOW + seconds})}.sig"


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b"{}"))


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


@pytest.fixture
def creds_file(tmp_path):
    f = tmp_path / "credentials.json"
    f.write_text(json.dumps({"api_url": "http://x", "token": "old", "refresh_token": "r1"}))
    os.chmod(f, 0o600)
    return f


def manager(creds_file, token, *, post, clock=None, refresh_token="r1"):
    # the file holds what the daemon started with
    creds_file.write_text(json.dumps(
        {"api_url": "http://x", "token": token, "refresh_token": refresh_token}))
    return TokenManager(api_url="http://x", token=token, refresh_token=refresh_token,
                        credentials_file=creds_file, post=post, clock=clock or Clock())


# ── proactive refresh ────────────────────────────────────────────────────

def test_refreshes_when_less_than_24h_left_and_persists_rotated_tokens(creds_file):
    new = jwt_expiring_in(7 * 24 * HOUR)
    post = mock.Mock(return_value={"token": new, "refresh_token": "r2"})
    m = manager(creds_file, jwt_expiring_in(2 * HOUR), post=post)
    m.ensure_fresh()
    post.assert_called_once_with("http://x/api/auth/cli/refresh", {"refresh_token": "r1"})
    assert m.access_token == new
    saved = json.loads(creds_file.read_text())
    assert saved["token"] == new and saved["refresh_token"] == "r2"
    assert saved["api_url"] == "http://x"  # other fields kept
    assert stat.S_IMODE(os.stat(creds_file).st_mode) == 0o600


def test_no_refresh_when_plenty_of_time_left(creds_file):
    post = mock.Mock()
    manager(creds_file, jwt_expiring_in(3 * 24 * HOUR), post=post).ensure_fresh()
    post.assert_not_called()


def test_static_keys_are_never_refreshed(creds_file):
    post = mock.Mock()
    manager(creds_file, "dev-daemon-key-local-only", post=post).ensure_fresh()
    post.assert_not_called()


def test_expired_token_is_refreshed_too(creds_file):
    post = mock.Mock(return_value={"token": "n", "refresh_token": "r2"})
    manager(creds_file, jwt_expiring_in(-5 * HOUR), post=post).ensure_fresh()
    post.assert_called_once()


def test_from_credentials_only_for_the_login_token(creds_file):
    assert TokenManager.from_credentials(
        credentials_file=creds_file, api_url="http://x", api_key="old") is not None
    assert TokenManager.from_credentials(
        credentials_file=creds_file, api_url="http://x", api_key="other-key") is None


# ── reactive refresh on 401 (REST client) ────────────────────────────────

def _client(auth):
    from agentira_cli.transport.rest import AgentiraClient
    return AgentiraClient(base_url="http://x", api_key="old", auth=auth)


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_401_refreshes_and_retries_exactly_once(creds_file):
    post = mock.Mock(return_value={"token": "new", "refresh_token": "r2"})
    m = manager(creds_file, "old", post=post)
    seen = []

    def urlopen(req, **kw):
        seen.append(req.get_header("Authorization"))
        if req.get_header("Authorization") == "Bearer old":
            raise http_error(401)
        return FakeResp(b'{"updated": 1}')

    with mock.patch("urllib.request.urlopen", urlopen):
        out = _client(m).heartbeat_runtimes("d", ["claude"])
    assert out == {"updated": 1}
    assert seen == ["Bearer old", "Bearer new"]
    assert post.call_count == 1


def test_still_401_after_refresh_raises_without_looping(creds_file):
    post = mock.Mock(return_value={"token": "new", "refresh_token": "r2"})
    m = manager(creds_file, "old", post=post)
    calls = []

    def urlopen(req, **kw):
        calls.append(1)
        raise http_error(401)

    with mock.patch("urllib.request.urlopen", urlopen), pytest.raises(urllib.error.HTTPError):
        _client(m).heartbeat_runtimes("d", ["claude"])
    assert len(calls) == 2 and post.call_count == 1


def test_non_401_errors_do_not_trigger_refresh(creds_file):
    post = mock.Mock()
    m = manager(creds_file, "old", post=post)
    with mock.patch("urllib.request.urlopen", side_effect=http_error(500)), \
            pytest.raises(urllib.error.HTTPError):
        _client(m).heartbeat_runtimes("d", [])
    post.assert_not_called()


def test_client_without_auth_behaves_as_before():
    with mock.patch("urllib.request.urlopen", side_effect=http_error(401)) as u, \
            pytest.raises(urllib.error.HTTPError):
        _client(None).heartbeat_runtimes("d", [])
    assert u.call_count == 1


def test_second_thread_reuses_the_token_the_first_already_renewed(creds_file):
    post = mock.Mock(return_value={"token": "new", "refresh_token": "r2"})
    m = manager(creds_file, "old", post=post)
    assert m.refresh("old") is True
    assert m.refresh("old") is True   # a racing caller that still holds "old"
    assert post.call_count == 1       # a 2nd exchange would trip reuse-detection


# ── failure: one clear ERROR per 10 minutes, backoff, recovery ───────────

def test_failed_refresh_logs_one_error_per_ten_minutes(creds_file, caplog):
    clock = Clock()
    post = mock.Mock(side_effect=http_error(401))
    m = manager(creds_file, "old", post=post, clock=clock)
    with caplog.at_level(logging.ERROR, logger="agentira.daemon.auth"):
        for _ in range(40):                 # 40 × 30s = 20 minutes of heartbeats
            m.refresh("old")
            clock.t += 30
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert errors == [SIGNED_OUT_MSG, SIGNED_OUT_MSG]   # t=0 and t=10min
    assert "agentira daemon login" in errors[0]


def test_failed_refresh_backs_off_but_keeps_retrying(creds_file):
    clock = Clock()
    post = mock.Mock(side_effect=http_error(401))
    m = manager(creds_file, "old", post=post, clock=clock)
    for _ in range(120):                    # one hour of 30s heartbeats
        m.refresh("old")
        clock.t += 30
    assert 3 <= post.call_count <= 12       # not every beat, but not given up


def test_recovers_when_the_server_comes_back(creds_file):
    clock = Clock()
    post = mock.Mock(side_effect=[http_error(401),
                                  {"token": "new", "refresh_token": "r2"}])
    m = manager(creds_file, "old", post=post, clock=clock)
    assert m.refresh("old") is False
    clock.t += 31
    assert m.refresh("old") is True and m.access_token == "new"


def test_server_down_is_reported_differently_from_signed_out(creds_file, caplog):
    m = manager(creds_file, "old", post=mock.Mock(side_effect=OSError("down")))
    with caplog.at_level(logging.ERROR, logger="agentira.daemon.auth"):
        assert m.refresh("old") is False
    [msg] = [r.getMessage() for r in caplog.records]
    assert "could not reach" in msg and "keep retrying" in msg


def test_legacy_login_without_refresh_token_says_signed_out(creds_file, caplog):
    post = mock.Mock()
    m = manager(creds_file, "old", post=post, refresh_token="")
    with caplog.at_level(logging.ERROR, logger="agentira.daemon.auth"):
        assert m.refresh("old") is False
    post.assert_not_called()
    assert [r.getMessage() for r in caplog.records] == [SIGNED_OUT_MSG]


def test_running_daemon_picks_up_a_fresh_daemon_login(creds_file):
    m = manager(creds_file, "old", post=mock.Mock(side_effect=http_error(401)))
    creds_file.write_text(json.dumps(
        {"api_url": "http://x", "token": "brand-new", "refresh_token": "rN"}))
    assert m.refresh("old") is True
    assert m.access_token == "brand-new"


def test_failed_save_does_not_regress_to_the_old_file_token(creds_file):
    post = mock.Mock(return_value={"token": "new", "refresh_token": "r2"})
    m = manager(creds_file, "old", post=post)
    with mock.patch("os.replace", side_effect=OSError("disk full")):
        assert m.refresh("old") is True
    assert m.access_token == "new"
    assert m.refresh("old") is True     # stale file ("old") is not re-adopted
    assert m.access_token == "new"


# ── daemon + WS wiring ───────────────────────────────────────────────────

def test_heartbeat_renews_proactively_first():
    from agentira_cli.daemon.core import AgentiraDaemon
    d = AgentiraDaemon.__new__(AgentiraDaemon)
    d._registered = [{"provider": "claude"}]
    d._daemon_id = "d"
    d._auth = mock.Mock()
    d.client = mock.Mock()
    order = mock.Mock()
    order.attach_mock(d._auth.ensure_fresh, "fresh")
    order.attach_mock(d.client.heartbeat_runtimes, "beat")
    d._heartbeat()
    assert [c[0] for c in order.mock_calls] == ["fresh", "beat"]


def test_ws_auth_rejection_triggers_refresh_before_reconnect():
    import queue
    import threading
    from agentira_cli.daemon.ws_client import DaemonWsClient, _is_auth_rejection

    class Closed(Exception):
        def __init__(self, code):
            self.rcvd = mock.Mock(code=code)

    assert _is_auth_rejection(Closed(4401))
    assert not _is_auth_rejection(Closed(1006))
    wrapped = ConnectionError("no ack")
    wrapped.__cause__ = Closed(4401)
    assert _is_auth_rejection(wrapped)
    resp = mock.Mock(status_code=401)
    assert _is_auth_rejection(type("InvalidStatus", (Exception,), {"response": resp})())

    auth = mock.Mock(access_token="old")
    c = DaemonWsClient("http://x", "old", "d", [], threading.Event(), queue.Queue(), auth=auth)

    def boom():
        c._stop.set()
        raise wrapped

    c._connect_and_listen = boom
    c._run()
    auth.refresh.assert_called_once_with("old")


# ── login stores the refresh token ───────────────────────────────────────

def test_login_saves_refresh_token_with_0600(tmp_path, monkeypatch):
    from agentira_cli.commands import daemon as cmd
    creds = tmp_path / "credentials.json"
    monkeypatch.setattr(cmd, "CREDENTIALS_FILE", creds)
    monkeypatch.setattr(cmd, "ensure_home", lambda: None)
    monkeypatch.setattr(cmd, "_device_info",   # never touch the real ~/.agentira
                        lambda: {"device_name": "Ali's Mac", "daemon_id": "d-1"})
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    monkeypatch.setattr("time.sleep", lambda s: None)
    sent = []

    def fake_post(url, body):
        sent.append((url, body))
        if url.endswith("/start"):
            return {"device_code": "dc", "user_code": "uc",
                    "verification_uri": "http://ui/cli-auth", "interval": 0, "expires_in": 60}
        return {"status": "approved", "token": "jwt", "refresh_token": "rt"}

    monkeypatch.setattr(cmd, "_post_json", fake_post)
    cmd.login(api_url="http://x")
    saved = json.loads(creds.read_text())
    assert saved == {"api_url": "http://x", "token": "jwt", "refresh_token": "rt"}
    assert stat.S_IMODE(os.stat(creds).st_mode) == 0o600
    start_body = sent[0][1]
    assert start_body == {"device_name": "Ali's Mac", "daemon_id": "d-1"}


def test_login_against_an_older_backend_still_works(tmp_path, monkeypatch):
    from agentira_cli.commands import daemon as cmd
    creds = tmp_path / "credentials.json"
    monkeypatch.setattr(cmd, "CREDENTIALS_FILE", creds)
    monkeypatch.setattr(cmd, "ensure_home", lambda: None)
    monkeypatch.setattr(cmd, "_device_info",   # never touch the real ~/.agentira
                        lambda: {"device_name": "Ali's Mac", "daemon_id": "d-1"})
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(cmd, "_post_json", lambda url, body: (
        {"device_code": "dc", "user_code": "uc", "verification_uri": "http://ui/cli-auth",
         "interval": 0, "expires_in": 60} if url.endswith("/start")
        else {"status": "approved", "token": "jwt"}))
    cmd.login(api_url="http://x")
    assert json.loads(creds.read_text()) == {"api_url": "http://x", "token": "jwt"}
