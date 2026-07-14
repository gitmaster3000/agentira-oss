"""AP-446: the Railway transport itself — headers and error classification.

`test_deploy_railway.py` fakes the transport to test adapter logic. This file
tests `RailwayApi` (the thing that actually speaks HTTP), because that is where
the production bug lived: Railway sits behind Cloudflare, which rejects the
stdlib's default `Python-urllib/3.x` User-Agent with `HTTP 403 error code: 1010`
*before* the token is ever looked at. Every token — valid or not — came back
"invalid", and no test caught it because no test exercised the real request.

`urlopen` is patched, so this stays offline.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from backend.deploy.railway import (
    USER_AGENT,
    ApiError,
    AuthError,
    BlockedError,
    RailwayApi,
    RailwayAdapter,
    TransportError,
)


class _Response(io.BytesIO):
    """Minimal stand-in for the object `urlopen` yields."""
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok(payload: dict):
    return _Response(json.dumps(payload).encode())


def _http_error(code: int, body: bytes):
    return urllib.error.HTTPError(
        "https://backboard.railway.com/graphql/v2", code, "err", {},
        io.BytesIO(body))


# ── the bug: Cloudflare bans the default urllib User-Agent ────────────────

def test_call_sends_a_real_user_agent():
    """Railway's WAF 403s `Python-urllib/3.x` (error code 1010). We must send
    our own UA on every request."""
    with patch("urllib.request.urlopen", return_value=_ok({"data": {"me": {}}})) as urlopen:
        RailwayApi().call("query { me { id } }", {}, token="tok")

    request = urlopen.call_args[0][0]
    sent = request.get_header("User-agent")
    assert sent == USER_AGENT
    assert "urllib" not in sent.lower()


def test_cloudflare_block_is_not_reported_as_a_bad_token():
    """A WAF block says nothing about the token. It must raise BlockedError —
    which is a TransportError, not an AuthError — so the token is never
    labelled invalid because of it."""
    with patch("urllib.request.urlopen",
               side_effect=_http_error(403, b"error code: 1010\n")):
        with pytest.raises(BlockedError) as exc:
            RailwayApi().call("query { me { id } }", {}, token="tok")

    assert isinstance(exc.value, TransportError)
    assert not isinstance(exc.value, AuthError)
    assert "1010" in str(exc.value)


def test_blocked_token_verifies_as_unknown_not_invalid():
    """End of the same story, at the adapter: a good token behind a WAF block
    must read as "couldn't check", never as "invalid"."""
    with patch("urllib.request.urlopen",
               side_effect=_http_error(403, b"error code: 1010\n")):
        valid, detail = RailwayAdapter().verify_credential("good-token")

    assert valid is None
    assert "could not reach Railway" in detail


# ── error classification ──────────────────────────────────────────────────

def test_401_is_an_auth_error():
    with patch("urllib.request.urlopen",
               side_effect=_http_error(401, b"Unauthorized")):
        with pytest.raises(AuthError):
            RailwayApi().call("query { me { id } }", {}, token="bad")


def test_graphql_not_authorized_is_an_auth_error():
    """Railway answers HTTP 200 with an `errors` payload for an unauthorized
    field — a team token hitting `me`, for instance."""
    payload = {"errors": [{"message": "Not Authorized"}], "data": None}
    with patch("urllib.request.urlopen", return_value=_ok(payload)):
        with pytest.raises(AuthError):
            RailwayApi().call("query { me { id } }", {}, token="team-tok")


def test_unreachable_is_a_transport_error():
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("connection refused")):
        with pytest.raises(TransportError):
            RailwayApi().call("query { me { id } }", {}, token="tok")


def test_invalid_json_is_a_transport_error():
    with patch("urllib.request.urlopen", return_value=_Response(b"<html>502</html>")):
        with pytest.raises(TransportError):
            RailwayApi().call("query { me { id } }", {}, token="tok")


def test_every_transport_failure_is_an_api_error():
    """Callers that only catch ApiError keep working."""
    for exc in (AuthError, TransportError, BlockedError):
        assert issubclass(exc, ApiError)


# ── logging: diagnosable without leaking the token ────────────────────────

def test_failures_are_logged_without_the_token(caplog):
    with patch("urllib.request.urlopen",
               side_effect=_http_error(403, b"error code: 1010\n")):
        with caplog.at_level("WARNING", logger="deploy.railway"):
            with pytest.raises(BlockedError):
                RailwayApi().call("query { me { id } }", {}, token="sup3r-s3cret")

    log = caplog.text
    assert "sup3r-s3cret" not in log
    assert "1010" in log
