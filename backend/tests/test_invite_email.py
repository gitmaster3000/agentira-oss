"""Admin invite sends the invite link by email when an address is given,
and reports honestly what happened (sent / not configured / failed / none)."""
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


@pytest.fixture
def smtp_on(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")


def test_invite_with_email_sends_link(client, smtp_on):
    with patch.object(email_sender, "send_email", return_value=True) as send:
        r = client.post("/api/invites", json={"email": "new@x.io"})
    assert r.status_code == 200
    body = r.json()
    assert body["email_sent"] is True
    assert body["email_status"] == "sent"
    to, subject, text = send.call_args.args
    assert to == "new@x.io"
    assert f"/signup?invite={body['code']}" in text


def test_invite_without_email_sends_nothing(client, smtp_on):
    with patch.object(email_sender, "send_email") as send:
        r = client.post("/api/invites", json={})
    assert r.status_code == 200
    assert r.json()["email_sent"] is False
    assert r.json()["email_status"] == "none"
    assert not send.called


def test_invite_email_failure_still_returns_invite(client, smtp_on):
    with patch.object(email_sender, "send_email", return_value=False):
        r = client.post("/api/invites", json={"email": "new@x.io"})
    assert r.status_code == 200
    assert r.json()["email_sent"] is False
    assert r.json()["email_status"] == "failed"
    assert r.json()["code"]


def test_invite_reports_email_not_configured(client, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with patch.object(email_sender, "send_email") as send:
        r = client.post("/api/invites", json={"email": "new@x.io"})
    assert r.status_code == 200
    body = r.json()
    assert body["email_sent"] is False
    assert body["email_status"] == "not_configured"
    assert body["code"]
    assert not send.called


def test_list_invites_shows_status(client, monkeypatch):
    from datetime import timedelta
    from backend import services
    from backend.db import privileged, SessionLocal
    from backend.models import Invite

    monkeypatch.delenv("SMTP_HOST", raising=False)
    client.post("/api/invites", json={"email": "pending@x.io"})
    old = client.post("/api/invites", json={"email": "old@x.io"}).json()
    done = client.post("/api/invites", json={"email": "done@x.io"}).json()
    with privileged(), SessionLocal() as db:
        o = db.query(Invite).filter(Invite.code == old["code"]).one()
        o.expires_at = services._utcnow() - timedelta(days=1)
        d = db.query(Invite).filter(Invite.code == done["code"]).one()
        d.accepted_at = services._utcnow()
        db.commit()

    r = client.get("/api/invites")
    assert r.status_code == 200
    by_email = {i["email"]: i for i in r.json()}
    assert by_email["pending@x.io"]["status"] == "pending"
    assert by_email["pending@x.io"]["code"]
    assert by_email["old@x.io"]["status"] == "expired"
    assert by_email["done@x.io"]["status"] == "accepted"
    assert "code" not in by_email["done@x.io"]
