"""Admin invite sends the invite link by email when an address is given."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import email_sender
from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    yield c


def test_invite_with_email_sends_link(client):
    with patch.object(email_sender, "send_email", return_value=True) as send:
        r = client.post("/api/invites", json={"email": "new@x.io"})
    assert r.status_code == 200
    body = r.json()
    assert body["email_sent"] is True
    to, subject, text = send.call_args.args
    assert to == "new@x.io"
    assert f"/signup?invite={body['code']}" in text


def test_invite_without_email_sends_nothing(client):
    with patch.object(email_sender, "send_email") as send:
        r = client.post("/api/invites", json={})
    assert r.status_code == 200
    assert r.json()["email_sent"] is False
    assert not send.called


def test_invite_email_failure_still_returns_invite(client):
    with patch.object(email_sender, "send_email", return_value=False):
        r = client.post("/api/invites", json={"email": "new@x.io"})
    assert r.status_code == 200
    assert r.json()["email_sent"] is False
    assert r.json()["code"]
